# HealthGMP — Vietnamese Chatbot (prototype + model-comparison rig)

A Vietnamese-first, knowledge-grounded chatbot for **HealthGMP** (Công ty Cổ phần
Sức khỏe GMP Việt Nam). One shared "brain" serves customers (B2C) and partner
distributor staff (B2B). It is a **model-comparison rig** that shares its core
logic with the eventual production back end — a config flag apart.

## What it does

- **Product Q&A** grounded ONLY in `data/products/*.md` (8 HGMP supplements).
- **General wellness Q&A** (meal plans, training, sleep habits, health tips) —
  answered in an educational tone.
- **Medical safety gate**: personal/clinical questions are escalated to a human
  *before* the model is called (never answered by the bot).
- **Switch AI models in the UI**: pick which model to chat with — API keys are read
  server-side from `secrets.toml` and are never shown or entered in the UI.
  Gemini / Groq / Cerebras / OpenRouter out of the box (OpenRouter reaches frontier
  models — Claude, GPT — with one key).

## Architecture (same logic as production)

```
Streamlit UI (app.py)
      │  builds ChatRequest {message, session_id, audience, config}
      ▼
orchestrator.handle_chat(req, settings)         ← the shared core
  1. guardrail.classify_question()  ─ medical gate BEFORE generation
  2. retrieval.retrieve()           ─ KB grounding (curated keyword map; Chroma path ready)
  3. gateway.complete()             ─ LiteLLM, model chosen at runtime (never hardcoded)
  4. escalation.parse_route()       ─ in-prompt ROUTE tag → tiered notification
      │  returns ChatResponse {answer, route, sources, model_used, config}
      ▼
Streamlit renders answer + model_used + sources + route
```

A FastAPI back end would wrap `orchestrator.handle_chat` unchanged — same
contract (`contract.py`), same prompts, same KB, same retrieval.

| File | Role |
|---|---|
| `contract.py` | pydantic request/response contract (the stable spine) |
| `gateway.py` | LiteLLM model gateway + provider registry + offline stub |
| `retrieval.py` | KB grounding (keyword map; vector RAG planned past ~20 products, HANDOFF §7) |
| `guardrail.py` | pre-generation medical gate (tuned: wellness passes, personal-medical escalates) |
| `prompts.py` + `prompts/*.md` | Vietnamese system prompt + guardrail classifier prompt |
| `orchestrator.py` | the core request handler |
| `escalation.py` | ROUTE parsing + escalation/feedback ticket logging (webhook or CSV) |
| `app.py` | Streamlit UI + model switcher |
| `eval/` | promptfoo comparison rig (runs the real pipeline per model) |

## Run locally

```bash
cd chatbot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # optional: prefill keys
streamlit run app.py
```

Put your key(s) in `.streamlit/secrets.toml` (copy from the example). The sidebar
then lets you pick **which model** to chat with (only providers with a key appear),
plus **audience** (B2C/B2B) and **mode** (`full` = prod behaviour). The UI never
shows or accepts keys. No keys yet? Pick **"Offline (demo)"** to click through the
flow with canned replies.

Get keys: Gemini (AI Studio) → https://aistudio.google.com/apikey · Groq →
https://console.groq.com/keys · Cerebras → https://cloud.cerebras.ai/ · OpenRouter →
https://openrouter.ai/keys

## Test

```bash
python -m pytest -q                       # unit + offline e2e tests, no key needed
cd eval && promptfoo eval && promptfoo view   # live model comparison + guardrail regression (needs keys)
```

## Deploy (stakeholder testing)

1. Push to GitHub — confirm `.streamlit/secrets.toml` is **not** committed.
2. share.streamlit.io → connect repo → main file `chatbot/app.py` → in **Secrets**
   add your provider key(s), `APP_PASSWORD`, and `LOG_WEBHOOK_URL` → deploy → share.
3. CSV logs reset on Streamlit Cloud restarts — set `LOG_WEBHOOK_URL` (Apps Script
   webhook, see below) so conversations/escalations persist in your Google Sheet.

## Logging & access control

**Access:** set `APP_PASSWORD` in secrets to gate the shared link — testers enter it
once. Leave empty for no gate (e.g. local dev).

**Logging:** every conversation turn, escalation ticket, and feedback note is
recorded. Destinations, in priority order:

1. **Webhook → Google Sheet (recommended — free, no GCP).** Deploy
   `tools/apps_script_logger.gs` as an Apps Script Web App on a normal Google Sheet
   and put its `/exec` URL in `LOG_WEBHOOK_URL`. Logs land in `conversations`,
   `escalations`, and `feedback` tabs (auto-created). Persists on Streamlit Cloud.
2. **Local CSV fallback** (`data/*.csv`) — zero setup, but ephemeral on Streamlit
   Cloud (resets on restart).

## Knowledge base & compliance

- One `.md` per product in `data/products/`. Detailed: Hetik, Femakul, Hemky,
  Hemky-D, Gueva, Niasom. Stubbed pending official specs: Binifa EX, Binifa Baby.
- Product claims were rewritten into compliant "hỗ trợ" language; the original
  disease-treatment claims from the marketing sites are flagged for legal review
  in `../2026-06-12-hgmp-compliance-flags.md` (NOT fed to the bot).

## Owner inputs still needed

- Official product docs (to reconcile the scraped KB; fill Binifa specs/NPN).
- Permitted-claim wording from the Vietnamese product registration (source of truth).
- Healthcare-team escalation channel (Google Sheet vs email) + contact.
- Legal sign-off on the compliance rewrites before any consumer-facing launch.
```
