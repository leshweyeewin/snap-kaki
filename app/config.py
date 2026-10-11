"""Central config. Keeps all Google-service wiring in one place so it is
easy to pin model names / project IDs at deploy time."""
import os

# --- Google Cloud / Gemini ---
# No default project id: this is set per deployment, and a real one baked
# into source is one more thing to forget to change. Stub mode does not
# need it; anything that calls a Google service does, and fails loudly
# below if it is missing.
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-southeast1")

# Route google-genai through Vertex AI so Cloud Run authenticates with its
# service account instead of a long-lived API key. ADK reads these env vars
# directly, so set them here before any agent is constructed.
USE_VERTEX = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "true").lower() == "true"
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE" if USE_VERTEX else "FALSE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", LOCATION)
if PROJECT_ID:
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT_ID)

# Vision + reasoning model (multimodal). Pin to whatever the deploy env has.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
# Embedding model for the form-guidance RAG corpus.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-004")

# Dependency versions verified in the deploy env on 2026-10-10 and pinned in
# requirements.txt. Logged at startup so a silent rebuild that drifts to a new
# ADK major is visible in the Cloud Run logs instead of failing mysteriously.
PINNED_ADK = "2.11.0"
PINNED_GENAI = "2.29.0"

# --- Firestore (RAG corpus + session state) ---
FIRESTORE_COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "form_guidance")
SESSION_COLLECTION = os.environ.get("SESSION_COLLECTION", "sessions")

# --- Safety thresholds ---
# Below this confidence the gate refuses to give a next-step and escalates.
CONFIDENCE_FLOOR = float(os.environ.get("CONFIDENCE_FLOOR", "0.75"))
# Actions that always trigger the gate regardless of confidence.
IRREVERSIBLE_ACTIONS = {"submit", "pay", "confirm", "agree", "sign", "consent"}

# Toggle real Gemini calls off for local/offline demo runs.
USE_STUB = os.environ.get("USE_STUB", "false").lower() == "true"

if not USE_STUB and not PROJECT_ID:
    raise RuntimeError(
        "GOOGLE_CLOUD_PROJECT is not set. Export your own project id, or run "
        "with USE_STUB=true for the offline demo (no cloud project needed)."
    )

# --- Demo scope ---
# One form, nailed end to end. The corpus and the stub are both built against
# the CHAS application form, Dec 2025 revision, downloaded from chas.sg.
# Bump this when the corpus is re-checked against a newer revision; it is the
# Firestore partition key, so stale chunks stop being retrieved rather than
# silently mixing with new ones.
DEMO_FORM_ID = os.environ.get("DEMO_FORM_ID", "chas-application-2025-12")

# Languages the field-explainer will answer in. Keys are what the client sends.
SUPPORTED_LANGUAGES = {
    "en": "English",
    "zh": "Mandarin Chinese",
    "ms": "Malay",
    "ta": "Tamil",
    "hokkien": "Hokkien (romanised, conversational)",
}
DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "en")
