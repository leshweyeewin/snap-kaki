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
- `ask` — explain `field_key`, optionally answering `question`
- `done` — the user finished `field_key`; give the next step
- `next` — just give the next step
- `family` — draft the message asking a relative for help

Fields are addressed by `field_key` (the `key` in a scan's field list), never
by label. Labels are not unique: the real form carries "Name (in BLOCK
LETTERS, as in NRIC)" and "Mobile Number" twice, once in Section 1A for the
applicant and again in Section 1B for a family member. Keying off the label
ticked both at once — caught by running the live vision agent against the
published PDF, and now covered by a regression test.

---

## Deliberate scope

The vision is broad. The demo is **one form, nailed, end to end, deployed.**

SnapKaki explains what a form asks and flags when to get official help. It
does **not** give authoritative immigration, legal, or financial advice, and
it never completes a declaration on someone's behalf. The gate's
refuse-when-unsure behaviour is what makes the breadth safe.

### A note on the real CHAS form

The corpus is built against the **Dec 2025** revision, downloaded from
chas.sg and read field by field. Worth knowing if you are working from older
notes: that revision differs from the Jan 2023 one in ways that matter.
Dwelling Type no longer breaks down by room count — it is HDB Flat / Private
Housing / Institution / Others. Rental Status reads "Not Rented (e.g. bought
or owned)" rather than "Owned". And the declaration is **Section 2B**, not
Clause 11. Re-check the corpus against the PDF if chas.sg publishes again.

Two things did survive the revision, and both are load-bearing for the pitch.

There is still **no income field** — eligibility is assessed from IRAS and
CPF records you consent to in Section 2B, or from the Annual Value of the
home where a household has no income. Any "type your salary here" step would
be a scripted lie about the real form.

And the form still has an **interpreter line**: Section 3 asks for the name,
NRIC and contact number of an interpreter where the signatory does not read
English. The government already accepts that these forms cannot be completed
unaided by everyone who needs them, and built a human assist layer into the
paper. SnapKaki is the always-on digital version of that line — with the
honest difference that a human interpreter can witness a signature and
software cannot. Which is exactly where the gate stops.

### Known gaps

- One form. The corpus covers CHAS only; another form needs another corpus.
- The front end has no live camera preview — it uses the native camera via
  `capture="environment"`, which is the most reliable path across iOS Safari
  and Android Chrome.
- Non-English output is generated but has not been reviewed by native
  speakers. Treat the dialect support as a demo of the mechanism.
