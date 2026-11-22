"""
Al Kindi Clinics Center — live voice booking demo
=================================================
Twilio Conversation Relay + LiteLLM + DeepSeek V4.1 Flash.

Call flow (see also system_prompt.py / the recorded demo script at
workspace/freelance-leads/al-kindi-voice-demo-script.txt):
  Caller -> Twilio number -> TwiML Bin -> <ConversationRelay url="wss://<host>/ws">
  Twilio does STT + TTS. This server only does the thinking (DeepSeek)
  and sends text tokens back for Twilio to speak.

Protocol (Twilio Conversation Relay WebSocket):
  Incoming: {"type": "setup", ...} on connect,
            {"type": "prompt", "voicePrompt": "...", "last": true} when the
            caller finishes speaking,
            {"type": "interrupt"} when the caller interrupts,
            {"type": "dtmf", ...}, {"type": "error", ...}
  Outgoing: {"type": "text", "token": "...", "last": false} streamed as the
            LLM produces tokens, with "last": true on the final token.

No OpenAI is used anywhere in this demo. The LLM is DeepSeek only.
If DEEPSEEK_API_KEY is not set (or is still the placeholder), the server
still runs in MOCK mode and answers with a canned reply that follows the
booking script — so you can test the WebSocket wiring with no keys and
no money spent. Mock mode is logged loudly on startup; it is NOT the
live demo.
"""

import json
import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from system_prompt import (
    SARA_SYSTEM_PROMPT,
    SARA_SYSTEM_PROMPT_AR,
    WELCOME_GREETING,
    WELCOME_GREETING_AR,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("al-kindi-sara")

# --- Config -----------------------------------------------------------------
# LiteLLM model id. The "deepseek/" prefix tells LiteLLM to use the
# DeepSeek API (https://api.deepseek.com/v1). "deepseek-flash" is
# DeepSeek V4.1 Flash — $0.30 / $1.20 per 1M tokens peak
# ($0.15 / $0.60 off-peak), i.e. roughly a tenth of a cent per call.
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek/deepseek-flash")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
# "surrogate" sentinel: the real DeepSeek key lives in the Secure Vault
# (custom.deepseek) and is only reachable as a short-lived hsurr: token
# via authd; fetch a fresh one for every LLM call, never store it in a file.
USE_SURROGATE = DEEPSEEK_API_KEY.strip().lower() == "surrogate"
DEEPSEEK_API_KEY = "" if USE_SURROGATE else (DEEPSEEK_API_KEY if DEEPSEEK_API_KEY and "your-" not in DEEPSEEK_API_KEY else "")


def get_deepseek_key():
    """Return a live DeepSeek credential.

    Locally (this VM) the key lives in the Secure Vault (custom.deepseek)
    and is only reachable as a short-lived hsurr: surrogate via authd;
    fetch a fresh one for every LLM call, never store it in a file.
    On Render there is no Secure Vault, so a plain DEEPSEEK_API_KEY env
    var is used instead — and if the surrogate fetch fails for any
    reason, fall back to the plain env var rather than failing the call.
    """
    if USE_SURROGATE:
        try:
            import sys
            sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
            from dynamic_credentials import dynamic_credential_entry
            return dynamic_credential_entry("custom.deepseek")["surrogate"]
        except Exception:
            log.warning("Surrogate fetch failed; falling back to DEEPSEEK_API_KEY env var")
    return DEEPSEEK_API_KEY
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
PUBLIC_WS_URL = os.getenv("PUBLIC_WS_URL", "")  # e.g. wss://xxxx.ngrok.io/ws
PORT = int(os.getenv("PORT", "8000"))

MOCK_MODE = not (DEEPSEEK_API_KEY or USE_SURROGATE)

try:
    import litellm  # type: ignore

    litellm.suppress_debug_info = True
except ImportError:  # pragma: no cover - litellm is in requirements.txt
    litellm = None
    MOCK_MODE = True
    log.warning("litellm is not installed — running in MOCK mode")

app = FastAPI(title="Al Kindi — Sara voice booking demo (Twilio + DeepSeek)")


# --- Mock replies (no-key testing only) -------------------------------------
def mock_reply(user_text: str, history: list, lang: str = "en") -> str:
    """Canned reply that follows the recorded demo script, for testing
    the WebSocket wiring without a DeepSeek key. Never used in live mode."""
    if lang == "ar":
        if any(w in user_text for w in ("تنظيف", "تنظيفاً")):
            return (
                "ممتاز، لتنظيف الأسنان لدي موعد غداً في الحادية عشرة صباحاً، "
                "أو يوم السبت في الخامسة مساءً. أيهما يناسبك أكثر؟"
            )
        if "غداً" in user_text or "الحادية عشرة" in user_text:
            return "ممتاز. هل يمكنني أخذ اسمك الكامل ورقم الواتساب الخاص بك، من فضلك؟"
        return (
            "مرحباً، شكراً لاتصالك بمركز الكندي للعيادات، أنا سارة، مساعدة "
            "الحجز. كيف يمكنني مساعدتك اليوم؟ هل هو فحص، تنظيف، ألم في الأسنان، "
            "أو علاج آخر؟"
        )
    low = user_text.lower()
    if any(w in low for w in ("clean", "cleaning")):
        return (
            "Great, for a cleaning I have tomorrow at eleven in the morning, "
            "or Saturday at five in the evening. Which one works better for you?"
        )
    if "tomorrow" in low or "eleven" in low or "11" in low:
        return "Perfect. May I have your full name and your WhatsApp number, please?"
    if len(history) >= 4:
        return (
            "Thank you. You are booked for a cleaning tomorrow at eleven in the "
            "morning with Al Kindi Clinics Center. I will send the confirmation "
            "on WhatsApp now. Is there anything else I can help with?"
        )
    return (
        "Hello, thank you for calling Al Kindi Clinics Center, this is Sara, "
        "your booking assistant. How can I help you today? Is it a check-up, "
        "cleaning, tooth pain, or another treatment?"
    )


# --- LLM --------------------------------------------------------------------
async def draft_response(messages: list, lang: str = "en") -> Any:
    """Stream DeepSeek tokens (async generator of strings).

    In mock mode, yields a single canned reply instead.
    """
    if MOCK_MODE:
        user_text = messages[-1]["content"] if messages else ""
        history = [m for m in messages if m["role"] == "user"]
        yield mock_reply(user_text, history, lang)
        return

    response = await litellm.acompletion(
        model=DEEPSEEK_MODEL,
        messages=messages,
        api_key=get_deepseek_key(),
        stream=True,
        temperature=0.3,  # low: bookings must be predictable, not creative
        max_tokens=200,  # short spoken replies only
    )
    async for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


# --- HTTP endpoints ---------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "al-kindi-sara",
        "llm": DEEPSEEK_MODEL,
        "mock_mode": MOCK_MODE,
        "deepseek_key_configured": bool(DEEPSEEK_API_KEY or USE_SURROGATE),
        "twilio_number_configured": bool(TWILIO_PHONE_NUMBER),
    }


@app.get("/twiml", response_class=PlainTextResponse)
@app.post("/twiml", response_class=PlainTextResponse)
async def twiml():
    """Language menu, then Conversation Relay.

    Twilio calls this when the call comes in. It asks the caller to
    press 1 for English or 2 for Arabic, then hands the choice to
    /choose-language, which returns the <ConversationRelay> TwiML.
    No digit (or any other key) defaults to English.
    Note: on a trial account the caller first hears Twilio's trial
    message and must press any key before this TwiML is even fetched."""
    host = PUBLIC_WS_URL.rsplit("/ws", 1)[0] if PUBLIC_WS_URL else ""
    # Gather action is a plain HTTPS webhook, not the wss:// socket URL.
    host = host.replace("wss://", "https://").replace("ws://", "http://")
    action = f"{host}/choose-language" if host else "/choose-language"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        '  <Gather numDigits="1" timeout="5" action="'
        + action
        + '" method="POST">\n'
        '    <Say language="en-US">For English, press 1. For Arabic, press 2.</Say>\n'
        '    <Say language="ar-SA">للغة العربية، اضغط 2. For English, press 1.</Say>\n'
        "  </Gather>\n"
        '  <Redirect method="POST">/choose-language</Redirect>\n'
        "</Response>\n"
    )


def _relay_twiml(lang: str) -> str:
    """<ConversationRelay> TwiML for the chosen language."""
    ws_url = PUBLIC_WS_URL or "wss://REPLACE-WITH-YOUR-NGROK-DOMAIN/ws"
    if lang == "ar":
        ws_url = ws_url.split("?")[0] + "?lang=ar"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            "  <Connect>\n"
            f'    <ConversationRelay url="{ws_url}" '
            'language="ar-SA" interruptible="true" '
            f'welcomeGreeting="{WELCOME_GREETING_AR}" />\n'
            "  </Connect>\n"
            "</Response>\n"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Connect>\n"
        f'    <ConversationRelay url="{ws_url}" '
        'language="en-US" interruptible="true" '
        f'welcomeGreeting="{WELCOME_GREETING}" />\n'
        "  </Connect>\n"
        "</Response>\n"
    )


@app.post("/choose-language", response_class=PlainTextResponse)
async def choose_language(request: Request, Digits: str = Form("")):
    """Twilio posts the caller's keypress here. 2 = Arabic, anything
    else (including no press) = English."""
    lang = "ar" if (Digits or "").strip() == "2" else "en"
    log.info("Language choice: digit=%r -> %s", Digits, lang)
    return _relay_twiml(lang)


# --- Conversation Relay WebSocket -------------------------------------------
@app.websocket("/ws")
async def conversation_relay(websocket: WebSocket):
    await websocket.accept()
    lang = (websocket.query_params.get("lang") or "en").strip().lower()
    if lang not in ("en", "ar"):
        lang = "en"
    log.info("Conversation Relay connected (lang=%s)", lang)
    system_prompt = SARA_SYSTEM_PROMPT_AR if lang == "ar" else SARA_SYSTEM_PROMPT
    messages: list = [{"role": "system", "content": system_prompt}]
    current_task: Optional[Any] = None

    async def send_text_stream(reply_tokens: Any):
        full_reply = ""
        async for token in reply_tokens:
            full_reply += token
            await websocket.send_json({"type": "text", "token": token, "last": False})
        # Final token marks the end of this turn for Twilio.
        await websocket.send_json({"type": "text", "token": "", "last": True})
        return full_reply

    try:
        while True:
            data = json.loads(await websocket.receive_text())
            msg_type = data.get("type")

            if msg_type == "setup":
                log.info(
                    "Call setup: from=%s to=%s callSid=%s",
                    data.get("from"),
                    data.get("to"),
                    data.get("callSid"),
                )
                # The welcome greeting is spoken by Twilio from the
                # <ConversationRelay> welcomeGreeting attribute.

            elif msg_type == "prompt":
                # Only answer once the caller has finished speaking.
                if not data.get("last"):
                    continue
                user_text = (data.get("voicePrompt") or "").strip()
                if not user_text:
                    continue
                log.info("Caller: %s", user_text)
                messages.append({"role": "user", "content": user_text})

                # Cancel any reply still being generated (caller spoke over it).
                if current_task and not current_task.done():
                    current_task.cancel()

                async def _respond():
                    reply = await send_text_stream(draft_response(messages, lang))
                    messages.append({"role": "assistant", "content": reply})
                    log.info("Sara: %s", reply)

                import asyncio

                current_task = asyncio.create_task(_respond())
                await current_task

            elif msg_type == "interrupt":
                log.info("Caller interrupted Sara — cancelling in-flight reply")
                if current_task and not current_task.done():
                    current_task.cancel()

            elif msg_type == "dtmf":
                log.info("DTMF received: %s", data.get("digit"))

            elif msg_type == "error":
                log.warning("Conversation Relay error: %s", data)

            else:
                log.debug("Unhandled Conversation Relay message: %s", msg_type)

    except WebSocketDisconnect:
        log.info("Conversation Relay disconnected")
    except Exception:
        log.exception("WebSocket handler error")


if __name__ == "__main__":
    import uvicorn

    if MOCK_MODE:
        log.warning(
            "MOCK MODE: DEEPSEEK_API_KEY is not set — replies are canned "
            "script replies for wiring tests only. Set a real key in .env "
            "for the live demo."
        )
    else:
        log.info("Live mode: DeepSeek model %s", DEEPSEEK_MODEL)
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)
