import os

from dotenv import load_dotenv

load_dotenv()


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


class Config:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    ALLOWED_ORIGINS = _csv(os.environ.get("ALLOWED_ORIGINS", ""))

    WP_BASE_URL = os.environ.get("WP_BASE_URL", "").rstrip("/")
    # Local by Flywheel usa certificado self-signed; en local conviene VERIFY_SSL=false.
    WP_VERIFY_SSL = os.environ.get("WP_VERIFY_SSL", "true").lower() not in ("0", "false", "no")

    FAQ_SIMILARITY_THRESHOLD = float(os.environ.get("FAQ_SIMILARITY_THRESHOLD", "0.70"))
    RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "4"))
    RATE_LIMIT = os.environ.get("RATE_LIMIT", "8 per minute")
    MAX_MESSAGE_LEN = int(os.environ.get("MAX_MESSAGE_LEN", "500"))
    POSTS_WINDOW_MONTHS = int(os.environ.get("POSTS_WINDOW_MONTHS", "6"))

    FORCE_GEMINI_FAILURE = os.environ.get("FORCE_GEMINI_FAILURE", "").lower() in ("1", "true", "yes")

    # Secreto compartido con el webhook de GitHub para /deploy-webhook (ver
    # app/deploy.py) — nunca se define acá como default, solo vía env var.
    WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    FAQS_PATH = os.path.join(DATA_DIR, "faqs.json")
    FAQ_INDEX_PATH = os.path.join(DATA_DIR, "faq_index.npz")
    FAQ_IDS_PATH = os.path.join(DATA_DIR, "faq_index_ids.json")
    CONTENT_INDEX_PATH = os.path.join(DATA_DIR, "content_index.npz")
    CONTENT_META_PATH = os.path.join(DATA_DIR, "content_meta.json")

    # Confirmado disponible en fastembed's model registry (a diferencia de
    # intfloat/multilingual-e5-small, que no existe ahí): 384 dim, liviano
    # para CPU compartida, no usa prefijos query:/passage: (modelo simétrico).
    EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    FALLBACK_MESSAGE = (
        "En este momento no puedo responder tu consulta. "
        "Por favor escribinos a administracion@ipesfa-ushuaia.edu.ar y te ayudamos."
    )
