# SnapKaki

**Point your phone at a confusing form. Get one clear next step — and a hard
stop before anything you cannot undo.**

| | |
|---|---|
| **Live app** | **https://snapkaki.web.app** |
| API service | https://snapkaki-1016762985649.asia-southeast1.run.app |
| Why it exists | [docs/why.md](docs/why.md) |
| Architecture and the decisions behind it | [docs/architecture.md](docs/architecture.md) |

The app is served from Firebase Hosting, which rewrites `/session`, `/turn`
and `/api/**` through to the Cloud Run service. Both links above work; the
first is the one to use.

---

My father could not work out how to log out of his email, and later could
not interpret an employment onboarding form. Last month a visa form defeated
me — and I am a senior engineer with a Master's in AI.

Those are the same problem. Neither of us was beaten by a device; we were
beaten by a document that would not explain itself, where being wrong had a
cost we could not see the size of. Confusing forms are not an elderly
problem. They stop a retiree and a senior engineer at the same wall.

SnapKaki reads what a form **asks**, explains it in the user's language, one
step at a time — and refuses to walk anyone through a signature, a consent
clause or a submission. [The full case, and why translation, chatbots and
autofill do not close it, is in docs/why.md](docs/why.md).

The demo walks one form end to end: the **CHAS** application
(Singapore's Community Health Assist Scheme — a health subsidy card),
Dec 2025 revision.

---

## The four Google services

| Service | What it does here |
|---|---|
| **Gemini** (`gemini-2.5-flash`, via Vertex AI) | Multimodal. Reads the form photo; writes every explanation and step |
| **Firestore** | Vector search (`find_nearest`) over the grounding corpus, plus session state |
| **Cloud Run** | Hosts the FastAPI service |
| **Firebase Hosting** | Serves the mobile web client, rewriting the API through to Cloud Run |

Agents are orchestrated with **Google ADK** — one `LlmAgent` per sub-agent,
run through an ADK `Runner`.

## Three things worth knowing

**The gate is a function, not a prompt.** A prompt that says *always stop
before a signature* can be argued out of stopping. A function returning
`allow=False` cannot. It has no network call and its own tests.

**There is no field for a value.** The session schema stores field labels
and which ones are done. "SnapKaki never sees your details" is a property of
the schema, not a promise about encryption.

**It says when it does not know.** Every explanation comes from a checked
corpus for that specific form. Retrieval returns nothing → it says so,
rather than improvising. That refusal is what makes pointing this at a visa
form safe.

Each of these is argued properly, with the alternatives we rejected, in
[docs/architecture.md](docs/architecture.md).

---

## Run it locally

Stub mode needs no cloud project, no credentials and no network, and walks
the full flow including the gate.

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
USE_STUB=true uvicorn app.main:app --reload --port 8080
```

Open <http://127.0.0.1:8080>. Tests:

```bash
USE_STUB=true python -m pytest tests/ -q
```

53 tests. `tests/test_flow.py` walks the whole demo and asserts the gate
fires on the declaration instead of walking the user into a signature.

### With real Gemini and Firestore

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=asia-southeast1
export USE_STUB=false
python -m app.rag.ingest          # embed the corpus into Firestore
uvicorn app.main:app --port 8080
```

`ingest.py` prints the one-off `gcloud firestore indexes composite create`
command for the vector index; `find_nearest` fails until that index builds.

### Configuration

Everything is read from the environment — no values are committed here.
`GOOGLE_CLOUD_PROJECT` has no default on purpose, and startup fails with a
clear message if it is missing outside stub mode.

| Variable | Default | What it does |
|---|---|---|
| `USE_STUB` | `false` | `true` runs the whole flow offline |
| `GOOGLE_CLOUD_PROJECT` | *(none — required)* | Your GCP project id |
| `GOOGLE_CLOUD_LOCATION` | `asia-southeast1` | Region for Vertex AI and Firestore |
| `GOOGLE_GENAI_USE_VERTEXAI` | `true` | Authenticate by service account, not an API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Multimodal model |
| `EMBED_MODEL` | `text-embedding-004` | Embeddings for the corpus |
| `CONFIDENCE_FLOOR` | `0.75` | Below this the gate refuses to give a next step |
| `DEMO_FORM_ID` | `chas-application-2025-12` | Firestore partition key for the corpus |
| `DEFAULT_LANGUAGE` | `en` | Fallback for an unknown language code |

## Deploy

```bash
gcloud run deploy snapkaki \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --max-instances 3 \
  --set-env-vars USE_STUB=false,GOOGLE_GENAI_USE_VERTEXAI=TRUE

# .firebaserc is not in the repo (it names a deployment project), so either
# create it with `firebase use --add` or pass --project explicitly.
firebase deploy --only hosting --project your-project-id
```

`--max-instances 3` is deliberate: the endpoint is public and every scan is
a billed Gemini call, so the cap bounds the damage if the URL is scraped.

## API

| Endpoint | Purpose |
|---|---|
| `POST /session` | Start a session (`language`), returns `session_id` |
| `POST /turn` | One interaction. Multipart, so a camera frame and a text turn share a path |
| `GET /api/health` | Liveness, plus which model and whether stub mode is on |

Not `/healthz`: Google's frontend swallows that path on Cloud Run before it
reaches the container, so the request never appears in the service logs.

`/turn` takes `kind`:

- `scan` — image attached; read the form, then give the next step
- `ask` — explain `field_key`, optionally answering `question`
- `done` — the user finished `field_key`; give the next step
- `next` — just give the next step
- `family` — draft the message asking a relative for help

Fields are addressed by `field_key`, never by label. Labels are not unique:
the real form carries "Name (in BLOCK LETTERS, as in NRIC)" and "Mobile
Number" twice, once in Section 1A for the applicant and again in Section 1B
for a family member. Keying off the label ticked both at once — caught by
running the live vision agent against the published PDF, and now covered by
a regression test.

---

## Scope

The vision is broad. The demo is **one form, nailed, end to end, deployed.**

SnapKaki explains what a form asks and flags when to get official help. It
does **not** give legal, immigration or financial advice, and it never
completes a declaration on anyone's behalf. The gate's refuse-when-unsure
behaviour is what makes that breadth safe to claim.

### Known gaps

- One form. The corpus covers CHAS only; another form needs another corpus.
- Reading a dense page takes Gemini about ten seconds. See the latency note
  in [docs/architecture.md](docs/architecture.md#what-we-would-change).
- Non-English output has not been reviewed by native speakers. Treat the
  dialect support as a demonstration of the mechanism.
