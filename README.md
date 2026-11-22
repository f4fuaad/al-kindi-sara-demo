# Al Kindi Voice Booking Demo — Twilio + DeepSeek (live)

A **live** voice agent, not a recording. You call a real Twilio phone
number, and "Sara, booking assistant for Al Kindi Clinics Center"
answers, books a cleaning, takes your name and WhatsApp number, and
confirms it — the same flow as the recorded demo
(`workspace/freelance-leads/al-kindi-voice-demo-script.txt`).

Stack: **Twilio Conversation Relay** (phone line + speech-to-text +
text-to-speech) → **this Python server** (FastAPI WebSocket) →
**DeepSeek V4.1 Flash** via LiteLLM (the brain). No OpenAI anywhere.
No Fish Audio in v1 — the voice is Twilio's built-in voice.

## Cost

About **$0.085 per minute** of talk time:

| Piece | Cost |
|---|---|
| Twilio number (US local) | ~$1.15 / month |
| Twilio voice, inbound | $0.014 / min |
| Twilio Conversation Relay | $0.07 / min |
| DeepSeek V4.1 Flash | ~$0.001 / min — $0.30 / $1.20 per 1M tokens peak ($0.15 / $0.60 off-peak); a 2-minute booking call is only a few thousand tokens |

A demo of a few test calls costs **under $2**, covered by Twilio's
$15 free trial credit. DeepSeek needs a small top-up (a few dollars
is plenty for a demo).

## Deploy on Render (free, demo only)

This is the demo deploy — Syed agreed the free plan is fine because the
server only needs to be up when showing it to a client. A free Render
web service **sleeps after 15 minutes with no traffic** and takes about
a minute to wake on the next call; for a paying client use the $7/month
Starter plan, which stays awake.

`render.yaml` in this repo defines the free web service (build
`pip install -r requirements.txt`, start
`uvicorn server:app --host 0.0.0.0 --port $PORT`).

1. In Render, create a **New Web Service** from this GitHub repo
   (Render reads `render.yaml` automatically).
2. In the service's **Environment** tab set these env vars (names only —
   values come from your Twilio Console and DeepSeek dashboard, never
   from this repo):
   `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`,
   `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` (`deepseek/deepseek-flash`).
   Leave `PUBLIC_WS_URL` blank for the first deploy.
3. Deploy. Render gives the service a public URL, e.g.
   `https://al-kindi-sara-demo.onrender.com`. Check
   `https://<your-service>.onrender.com/health` — it must show
   `"mock_mode": false` and `"deepseek_key_configured": true`. If it
   shows mock mode, the DeepSeek key is missing or wrong.
4. Set `PUBLIC_WS_URL=wss://<your-service>.onrender.com/ws` in
   Render's Environment tab and redeploy/restart, so `/twiml` returns
   the real WebSocket URL. (On Render there is no Secure Vault, so
   `server.py` uses the plain `DEEPSEEK_API_KEY` env var; the
   surrogate path is only used locally when `.env` says `surrogate`.)
5. Point the Twilio number at it: either paste `twiml-bin.xml` into a
   TwiML Bin with `YOUR-PUBLIC-DOMAIN` replaced by your Render domain,
   or set the number's Voice webhook to
   `https://<your-service>.onrender.com/twiml`. Then call the number.

## Files

| File | What it is |
|---|---|
| `server.py` | FastAPI server: `/health`, `/twiml`, and the `/ws` Conversation Relay WebSocket. Streams DeepSeek tokens back to Twilio as `text` tokens. |
| `system_prompt.py` | Sara's system prompt: booking flow, the two slots only (tomorrow 11am, Saturday 5pm), no prices, handover rules (pain/emergency, insurance, real person, medical advice). |
| `requirements.txt` | fastapi, uvicorn, litellm, python-dotenv (+ httpx/pytest for tests). |
| `.env.example` | Placeholder keys only — copy to `.env` and fill in your own. **No real credential is in this repo.** |
| `twiml-bin.xml` | TwiML to paste into a Twilio TwiML Bin. |
| `test_server.py` | Tests the server with no keys and no money (see below). |

## Setup — step by step

### 1. Twilio trial account (Syed — you do this, ~5 min)
1. Go to https://www.twilio.com/try-twilio and sign up with your email.
2. Verify your phone number (Twilio sends a code). No card needed for the trial.
3. You get **$15 free credit**. Trial accounts can only call numbers you
   have verified in the Console — verify your own mobile number first.
4. In the Console, go to **Phone Numbers → Buy a Number**, pick a **US local**
   number with **Voice** capability (~$1.15/month, paid from the $15 credit).
   Qatar numbers are not sold by Twilio, so a US number is the demo number.
   (Optional but recommended: Console → Voice → ConversationRelay →
   Onboarding — Twilio may ask you to complete this before Conversation
   Relay works.)

### 2. DeepSeek API key (Syed — you do this, ~5 min)
1. Go to https://platform.deepseek.com/ and sign in (or create an account).
2. **API Keys → Create new API key**, copy it.
3. **Top up** a small amount (a few dollars) — DeepSeek is pay-as-you-go,
   and the demo uses a fraction of a cent per call.

### 3. Run the server (on your laptop, or this VM)
```bash
cd twilio-deepseek-demo
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then edit .env with your real keys
# In .env set: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
#              TWILIO_PHONE_NUMBER, DEEPSEEK_API_KEY
python server.py                # listens on http://localhost:8000
```
Check it is up: open http://localhost:8000/health — you should see
`"status": "ok"`, `"mock_mode": false`, `"deepseek_key_configured": true`.
If `mock_mode` is still `true`, the DeepSeek key is missing or still a
placeholder — the server will answer with canned script replies instead
of live DeepSeek replies, so fix `.env` before the test call.

### 4. Expose it with ngrok
```bash
ngrok http 8000
```
Copy the forwarding domain, e.g. `03ca546a6a10.ngrok.io` (no `https://`).

### 5. Point the Twilio number at the server
1. Console → **Develop → TwiML → TwiML Bins → Create new TwiML Bin**.
2. Paste the contents of `twiml-bin.xml`, replacing
   `YOUR-NGROK-DOMAIN` with your ngrok domain. Save.
3. Console → **Phone Numbers → Manage → your number → Voice Configuration**:
   set **"A call comes in"** to your TwiML Bin. Save.
   (Alternative: set the webhook to `https://<ngrok-domain>/twiml` —
   the server returns the same TwiML from `GET /twiml`.)

### 6. Test call
Call your Twilio number from your (verified) phone. You should hear:
> "Hello, thank you for calling Al Kindi Clinics Center, this is Sara,
> your booking assistant. How can I help you today?"

Say: *"I'd like a cleaning, please."* Sara should offer tomorrow 11am
or Saturday 5pm, then ask your name and WhatsApp number, then confirm
the booking and say she'll send the confirmation on WhatsApp.
Try breaking it too: ask for a price, or say you have tooth pain —
Sara must not invent a price or give medical advice, she must offer a
callback / handover instead.

## Testing without keys (already done here)

```bash
python test_server.py
```
Runs 3 checks in mock mode — `/health`, `/twiml`, and a full WebSocket
booking turn — with no Twilio/DeepSeek keys and no money spent. See
`test_server.py` for what each check asserts.

## What this demo does NOT do (v1 limits)
- No WhatsApp message is actually sent after booking — Sara only *says*
  she will send one. Sending it needs the WhatsApp Business API / Twilio
  WhatsApp, wired up in v2.
- No real calendar — the two slots (tomorrow 11am, Saturday 5pm) are
  fixed example slots, exactly as in the recorded demo.
- No Fish Audio voice — Twilio's built-in voice speaks Sara's replies.
- The server must stay running (and ngrok up) while you demo it. For a
  permanent number, deploy it to a small VPS / Render / Railway instead
  of ngrok.
- Trial Twilio accounts play a short trial message before each call and
  can only call verified numbers. Upgrade (free, pay-as-you-go) to remove
  that for real clinic use.
