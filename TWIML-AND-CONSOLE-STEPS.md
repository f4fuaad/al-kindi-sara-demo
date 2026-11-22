# Al Kindi live demo — TwiML Bin + Console steps (READY TO RUN, waiting on a public URL)

Status 2026-11-22: the server is RUNNING locally and VERIFIED LIVE
against real DeepSeek (see below). The tunnel route is now Render
(free plan, demo only — it sleeps after 15 min idle, which is fine
for a demo). The repo is `f4fuaad/al-kindi-sara-demo` with `render.yaml`.
Do NOT create the TwiML Bin or link the number until the Render
service has a public URL; the steps below are exact and ready to run
the moment it does.

## What is already done and verified

- `.env` written in `~/workspace/twilio-deepseek-demo/.env` (mode 0600):
  Twilio Account SID + Auth Token + number +1 256 418 8115, DeepSeek model
  `deepseek/deepseek-flash`, PORT 8000. No real DeepSeek key is in the file:
  `DEEPSEEK_API_KEY=surrogate` — server.py fetches a fresh short-lived
  surrogate from the Secure Vault (custom.deepseek) on every LLM call.
- Live DeepSeek test: `GET https://api.deepseek.com/v1/models` with the
  surrogate returned 200, listing `deepseek-flash`. A live
  `chat/completions` call with model `deepseek-flash` returned 200.
  NOTE: the DeepSeek API rejects `deepseek/deepseek-flash` as a model name
  (400) — LiteLLM strips the `deepseek/` prefix on the wire, so the server
  config stays `deepseek/deepseek-flash`.
- Live WebSocket test (in-process, real DeepSeek, no mock): Sara replied
  to "Hi, I'd like a cleaning, please." with:
  "Sure — I have tomorrow at eleven in the morning, or Saturday at five
  in the evening. Which one works better for you?"
- Server running NOW on this VM: `python3 server.py`, pid 10438,
  log `/tmp/sara-server.log`.
  `GET http://127.0.0.1:8000/health` returns:
  `{"status":"ok","service":"al-kindi-sara","llm":"deepseek/deepseek-flash","mock_mode":false,"deepseek_key_configured":true,"twilio_number_configured":true}`
- `server.py` patched (and py_compile clean): surrogate fetch per LLM call
  (`get_deepseek_key()`), `/health` reports the surrogate as configured.

## Step 1 — get a public URL (Render, free plan)

Deploy the repo on Render (see README "Deploy on Render (free, demo
only)"). Render gives the service a public URL, e.g.
`https://al-kindi-sara-demo.onrender.com`. Set
`PUBLIC_WS_URL=wss://<your-service>.onrender.com/ws` in Render's
Environment tab and redeploy/restart. The public WebSocket URL Twilio
needs is: `wss://<your-service>.onrender.com/ws`

(Old tunnel route — no longer used: ngrok from this VM is blocked
because ngrok free refuses the VM's egress proxy; Cloudflare quick
tunnel fails TLS via the proxy; localtunnel is unreachable.)

## Step 2 — TwiML Bin (browser task in Syed's own Chrome)

Console → Develop → TwiML → TwiML Bins → Create new TwiML Bin.
Paste EXACTLY this, replacing `YOUR-PUBLIC-DOMAIN` with the real Render
domain from Step 1 (no `https://`, no trailing slash). Save it.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <ConversationRelay url="wss://YOUR-PUBLIC-DOMAIN/ws"
                       language="en-US"
                       interruptible="true"
                       welcomeGreeting="Hello, thank you for calling Al Kindi Clinics Center, this is Sara, your booking assistant. How can I help you today?" />
  </Connect>
</Response>
```

## Step 3 — link the number (same browser task)

Console → Phone Numbers → Manage → Active numbers → +1 256 418 8115 →
Voice Configuration → "A call comes in" → select the TwiML Bin created
in Step 2. Save.

Alternative (no TwiML Bin): set "A call comes in" to Webhook
`https://<domain>/twiml` — the server returns the same TwiML from
`GET /twiml`.

## Step 4 — test call

Syed calls +1 256 418 8115 from his verified phone (trial accounts can
only be called from verified numbers, and play a short trial message
first). Sara should greet, then on "I'd like a cleaning, please" offer
tomorrow 11am or Saturday 5pm, then ask name + WhatsApp number, then
confirm. Keep the server AND the tunnel running for the whole demo;
both die when this VM/session ends, and the tunnel domain changes on
every restart (a new TwiML Bin edit is needed each time unless a
reserved ngrok domain / named Cloudflare tunnel is used).

## Blocker — no public tunnel from this VM (tried 2026-11-22 07:05–07:20)

- Cloudflare quick tunnel: fails every time —
  `failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel":
  tls: first record does not look like a TLS handshake`.
  Direct curl to api.trycloudflare.com gets 403 "Your request was blocked".
- ngrok 3.39.13: reaches ngrok fine, but refuses without an account:
  `ERR_NGROK_4018 — authentication failed: This ngrok session is not
  authenticated. ngrok requires an account and a valid credential.`
  No ngrok authtoken exists; creating an ngrok account was NOT authorised.
- localtunnel (npx): starts but never prints a URL; localtunnel.me is
  unreachable from this VM (curl code 000).
- SSH tunnels (localhost.run, serveo.net, bore.pub, pinggy.io via the
  egress proxy): SSH banner exchange / CONNECT times out; proxy CONNECT
  to pinggy.io:443 and api.trycloudflare.com:443 returns 200 but the
  SSH session never completes.
- A final tunnel-probe command returned a timed-out approval notice, so
  no further tunnel probing was retried.

Practical ways past this (needs Syed/parent decision, no money spent so far):
1. Syed creates a free ngrok account, gives the authtoken via the secure
   form, and the tunnel is started here with `ngrok config add-authtoken`.
2. Or run the server on Syed's own laptop and run ngrok/Cloudflare there
   (same `.env` + `server.py`, tunnel works from a normal network).
3. Or deploy the server to a small VPS/Render/Railway with a real domain.

## Costs so far

Nothing new spent. Twilio trial balance still $8.6434; number
$1.15/month. DeepSeek live test used ~46 tokens (fractions of a cent).
