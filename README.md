# SnapKaki

**Point your phone at a confusing form. Get one clear next step.**

Confusing forms are not an elderly problem. They are a *this form is
genuinely hard* problem. A senior engineer gets stuck on a visa form. The
real user is anyone facing a consequential form they do not fully
understand — the elderly are the sharpest case, not the whole market.

SnapKaki reads what a form **asks**, explains it in the user's language,
gives one next step at a time, and **stops before anything irreversible**.

The demo walks one form end to end: the **CHAS** application form
(Singapore's Community Health Assist Scheme — a health subsidy card).

---

## The four Google services

| Service | What it does here |
|---|---|
| **Gemini** (`gemini-2.5-flash`, via Vertex AI) | Multimodal. Reads the form photo; writes every explanation and step. |
| **Google ADK** (Agent Development Kit) | Each sub-agent is an ADK `LlmAgent` run through an ADK `Runner`. |
| **Firestore** | Vector store for the grounding corpus (`find_nearest`), plus session state. |
| **Cloud Run** | Hosts the FastAPI app and serves the mobile web front end from one origin. |

Firebase is used for hosting/auth only if the deployment grows past a single
Cloud Run service; today Cloud Run serves the front end directly, which keeps
`getUserMedia` and the API on the same origin and avoids a CORS hop.

---

## Architecture

```
          camera / screenshot
                  |
          FastAPI  (app/main.py)
                  |
          orchestrator  (app/orchestrator.py)   <- deterministic routing
                  |
    +-------------+-------------+---------------+--------------+
    |             |             |               |              |
  vision    field_explainer  guidance    confidence_gate   family_loop
 LlmAgent      LlmAgent      LlmAgent     plain Python       LlmAgent
                  |             |               |
              Firestore RAG  Firestore RAG   frozen rules
```

### Three decisions worth defending

**1. The confidence gate is not a model.**

Every other sub-agent is an `LlmAgent`. The gate
([`app/agents/confidence_gate.py`](app/agents/confidence_gate.py)) is a pure
Python function of `(action, confidence)`.

"SnapKaki never auto-submits and stops when it is unsure" is either a
guarantee or it is marketing. A prompt saying *always stop before a
signature* can be argued out of stopping — by a strange form, an insistent
user, or just sampling. A function returning `allow=False` when the action is
in a frozen set cannot. It is unit-tested, it has no network call, and it
behaves identically every run.

**2. Routing is deterministic, not LLM-chosen.**

The turn's shape picks the sub-agent. This costs flexibility and buys the
property that matters: the gate is a line of code on the way out, not a
sub-agent the router might forget to call.

**3. There is no field for a value.**

The user types their identification number into the paper form, not into
SnapKaki. The session schema ([`app/session.py`](app/session.py)) stores
field *labels*, kinds, printed options, and which labels are done. There is
nowhere to put a value, so "SnapKaki never sees your details" is structural
rather than promised. Redaction
([`app/redaction.py`](app/redaction.py)) is the backstop for text that slips
through — OCR output, pre-filled labels — and the vision agent is instructed
never to transcribe what a user has written, with its output re-scanned and
its confidence floored if it does anyway.

### Grounding

The field explainer may only speak from passages retrieved out of the
corpus ([`app/rag/corpus/chas.md`](app/rag/corpus/chas.md)). If retrieval
returns nothing, it says it does not know rather than improvising — and
that refusal is what makes the broad version of this product safe to point
at a visa form.

---

## Run it locally

Stub mode needs no cloud project, no credentials, and no network. It walks
the full CHAS flow including the gate.

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
USE_STUB=true uvicorn app.main:app --reload --port 8080
```

Open <http://127.0.0.1:8080>. Tests:

```bash
USE_STUB=true python -m pytest tests/ -q
```

`tests/test_flow.py` walks the whole demo and asserts the gate fires on the
declaration instead of walking the user into a signature.

### With real Gemini + Firestore

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=deskpilot-507116
export GOOGLE_CLOUD_LOCATION=asia-southeast1
export USE_STUB=false
python -m app.rag.ingest          # embed the corpus into Firestore
uvicorn app.main:app --port 8080
```

`ingest.py` prints the one-off `gcloud firestore indexes composite create`
command for the vector index; `find_nearest` fails until that index builds.

---

## Deploy to Cloud Run

```bash
gcloud run deploy snapkaki \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --set-env-vars USE_STUB=false,GOOGLE_GENAI_USE_VERTEXAI=TRUE
```

Prerequisites, once per project:

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  aiplatform.googleapis.com firestore.googleapis.com
gcloud firestore databases create --location=asia-southeast1
```

The service account needs `roles/aiplatform.user` and
`roles/datastore.user`.

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /session` | Start a session (`language`), returns `session_id`. |
| `POST /turn` | One interaction. Multipart, so a camera frame and a text turn share a path. |
| `GET /healthz` | Liveness, plus which model and whether stub mode is on. |

`/turn` takes `kind`:

- `scan` — image attached; read the form, then give the next step
- `ask` — explain `field_label`, optionally answering `question`
- `done` — the user finished `field_label`; give the next step
- `next` — just give the next step
- `family` — draft the message asking a relative for help

---

## Deliberate scope

The vision is broad. The demo is **one form, nailed, end to end, deployed.**

SnapKaki explains what a form asks and flags when to get official help. It
does **not** give authoritative immigration, legal, or financial advice, and
it never completes a declaration on someone's behalf. The gate's
refuse-when-unsure behaviour is what makes the breadth safe.

### A note on the real CHAS form

The real form has an **interpreter section**: a place for someone to sign
confirming they read and explained the form to a signatory who does not read
English. The government already accepts that these forms cannot be completed
unaided by everyone who needs them, and built a human assist layer into the
paper. SnapKaki is the always-on digital version of that section — with the
honest difference that a human interpreter can witness a signature and
software cannot. Which is exactly where the gate stops.

### Known gaps

- One form. The corpus covers CHAS only; another form needs another corpus.
- The front end has no live camera preview — it uses the native camera via
  `capture="environment"`, which is the most reliable path across iOS Safari
  and Android Chrome.
- Non-English output is generated but has not been reviewed by native
  speakers. Treat the dialect support as a demo of the mechanism.
