"""
Test the Al Kindi Sara server WITHOUT any real Twilio / DeepSeek keys.

Run:  python test_server.py
  or: pytest test_server.py -v

What it checks:
  1. GET /health returns 200 and reports mock_mode=true when no key is set.
  2. GET /twiml returns valid TwiML containing <ConversationRelay>.
  3. The WebSocket /ws accepts a connection, handles a "setup" message,
     answers a "prompt" ("Hi, I'd like a cleaning, please.") with streamed
     "text" tokens ending in last=true, and the reply offers the two demo
     slots (tomorrow 11am / Saturday 5pm) — the canned mock reply that
     follows the recorded demo script.

No network calls are made and no money is spent. With a real
DEEPSEEK_API_KEY in .env the same WebSocket test would hit DeepSeek
instead of the mock, so run these tests with NO .env present (or with
the placeholder key) to stay in mock mode.
"""

import json
import os
import sys

# Force mock mode: set a placeholder key BEFORE importing server, so
# load_dotenv() will not override it with a real/surrogate key from .env
# (load_dotenv does not overwrite existing env vars). server.py treats
# any "your-..." key as empty, so this forces mock mode even when a
# live .env is present in the same directory.
os.environ["DEEPSEEK_API_KEY"] = "your-placeholder-key-for-tests"
os.environ.pop("PUBLIC_WS_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from server import app  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm"] == "deepseek/deepseek-flash"
    assert body["mock_mode"] is True, "expected mock mode with no DeepSeek key"
    print("PASS  health:", body)


def test_twiml():
    r = client.get("/twiml")
    assert r.status_code == 200, r.text
    assert "<ConversationRelay" in r.text
    assert 'url="wss://' in r.text
    assert "Al Kindi" in r.text
    print("PASS  twiml returns <ConversationRelay> with a wss:// URL")


def test_websocket_booking_flow():
    with client.websocket_connect("/ws") as ws:
        # 1. Twilio sends "setup" first.
        ws.send_json(
            {
                "type": "setup",
                "callSid": "CAtest123",
                "from": "+97455551234",
                "to": "+14155550132",
            }
        )
        # 2. Caller speaks (partial prompts are ignored; only last=true answers).
        ws.send_json({"type": "prompt", "voicePrompt": "Hi, I'd like a", "last": False})
        ws.send_json(
            {"type": "prompt", "voicePrompt": "Hi, I'd like a cleaning, please.", "last": True}
        )
        # 3. Collect streamed text tokens until last=true.
        tokens, saw_last = [], False
        for _ in range(20):
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "text", msg
            tokens.append(msg.get("token", ""))
            if msg.get("last"):
                saw_last = True
                break
        assert saw_last, "never received a text token with last=true"
        reply = "".join(tokens)
        assert "tomorrow" in reply.lower() and "saturday" in reply.lower(), reply
        assert "eleven" in reply.lower() and "five" in reply.lower(), reply
        print("PASS  websocket booking flow — Sara replied:", reply)


if __name__ == "__main__":
    try:
        test_health()
        test_twiml()
        test_websocket_booking_flow()
    except AssertionError as e:
        print("FAIL:", e)
        sys.exit(1)
    print("\nAll 3 tests passed (mock mode, no keys, no money spent).")
