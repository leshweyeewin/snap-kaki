# SnapKaki

**Point your phone at a confusing form. Get one clear next step — and a hard
stop before anything you cannot undo.**

| | |
|---|---|
| **Live app** | **https://snapkaki.web.app** |
| API service | https://snapkaki-1016762985649.asia-southeast1.run.app |
| Architecture and the decisions behind it | [docs/architecture.md](docs/architecture.md) |

The app is served from Firebase Hosting, which rewrites `/session`, `/turn`
and `/api/**` through to the Cloud Run service. Both links above work; the
first is the one to use.

---

## Why SnapKaki exists

My mother struggles with her phone. Where things are, what a gesture does,
why the screen changed. The difficulty is the machine.

My father could not work out how to log out of his email. Later, an
employment onboarding form asked him for details he had no way to interpret.
He can read. He can tap. What defeated him was not the phone — it was that
nothing on the screen explained what it was actually asking for, or what
would happen if he got it wrong.

Last month a visa form defeated me. I am a senior engineer with a Master's
in AI. Not because I could not use a computer; because the form was opaque
and the cost of getting it wrong was real.

For a long time I read these as one problem with one name: *they are not
good with technology.* That reading is wrong, and it is wrong in a way that
matters, because it points at a solution that does not work.

My mother's problem is digital literacy — the device is unfamiliar, and the
fix is teaching, practice and better interface design. My father's
onboarding form and my visa form are **the same problem as each other**, and
it is a different one. Neither of us was blocked by the machine. We were
blocked by a document that would not explain itself, in a situation where
being wrong had a cost we could not see the size of. Strip away the age gap,
the language gap and the thirty years of computing experience between us,
and my father and I failed at the same wall.

> Confusing forms are not an elderly problem. They are a comprehension
> problem under consequence — and they stop a retiree and a senior engineer
> in exactly the same way.

The elderly are the sharpest and most sympathetic case. They are not the
market. The market is anyone holding a form they do not fully understand and
cannot afford to get wrong.

So we built for the second problem and not the first, and the reason is
honest rather than strategic: an AI assistant is a poor teacher of a device
it cannot see you holding, and a good explainer of a document you can show
it. Point a camera at a form and the whole problem is in frame. "Help my
mother learn her phone" is not a tractable thing to be useful about, and
pretending otherwise would produce a demo rather than a product.

SnapKaki reads what a form **asks**, explains it in the user's language, one
step at a time — and refuses to walk anyone through a signature, a consent
clause or a submission.

**On a phone:** open <https://snapkaki.web.app>. Nothing to install. Tap
*Point at the form* and your camera opens. To keep it, use your browser's
**Add to Home Screen** — it installs as an app, opens full-screen and keeps
its own icon.

Ask about any field in your own words, by typing or by voice. Dictation runs
in the browser and never leaves the phone, which is the same promise the rest
of the product makes. Any answer can be read aloud, in your language.

The demo walks one form end to end: the **CHAS** application
(Singapore's Community Health Assist Scheme — a health subsidy card),
Dec 2025 revision.

### Why the existing answers don't close it

Every one of these exists and is used. The two that matter most are the
family member and the chatbot.

**Asking a family member** is the real incumbent, and it mostly works. It
fails in three ways: they are at work when you are at the form; asking
repeatedly costs something, because my father does not like needing help
with a logout button and that reluctance is itself a reason forms go
unfiled; and often the family member does not know either — I did not know
what my own visa form was asking. SnapKaki does not try to replace this. It
routes *to* it, at the moment it is actually warranted, with a written
summary of where things stand. The hand-off is a feature, not a fallback.

**A general-purpose chatbot** is the closest competitor and the clearest
contrast. Paste the question into any capable assistant and you get a fluent
answer. But it will answer confidently from the wrong revision — the
published CHAS form changed between Jan 2023 and Dec 2025, and a model
answering from training data describes a form that no longer exists in
exactly the same register as a correct answer. It has no stopping behaviour:
ask it to walk you through a legal declaration and it will. And you have to
know what to ask, which assumes you already identified what you did not
understand — whereas pointing a camera does not.

> A general assistant optimises for answering. SnapKaki optimises for
> knowing when not to.

The rest solve adjacent problems, and it is worth being precise about which:

| | Solves | Leaves untouched |
|---|---|---|
| Helplines and service counters | Authoritative answers, free | Queues, opening hours, and you must already know you need help |
| Google Translate, camera translation | The **language** gap | The **comprehension** gap. "Rental Status of Residence" in flawless Mandarin is just as unhelpful — the hard part is that a flat you are still paying a housing loan on counts as *Not Rented*, and no dictionary contains that |
| Autofill, prefilled government services | Data entry, for people who **already understand** the form | Comprehension — and arguably makes it worse, since you end up having submitted something you never read |
| Screen readers, zoom, high contrast | **Perception** — making out what is on the page | Everything after you have read every word perfectly |

Singapore's own prefill services are genuinely excellent and remove most of
the typing. They do not explain the declaration, and the hardcopy path this
demo uses exists precisely for the people who cannot use them.

### What the form itself admits

The strongest argument that this need is real is printed on the form.

Section 3 of the CHAS application has a line for an **interpreter**: name,
identification number and contact number of the person who read and
explained the form to a signatory who does not read English. The government
already knows these documents cannot be completed unaided by everyone who
needs them, and has built a human assist layer into the paper itself.

SnapKaki is the always-on version of that line — with one honest difference,
and it is the one that defines the product. A human interpreter can witness
a signature. Software cannot. So at the signature, SnapKaki stops and asks
for a person.

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
