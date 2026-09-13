from flask import Blueprint, current_app, jsonify, request

from .config import Config
from .embeddings import embed_query
from .faq_matcher import match_faq
from .gemini_client import QuotaExceededError, call_gemini
from .rag import build_prompt, retrieve_context
from .rate_limit import limiter

chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/chat", methods=["POST"])
@limiter.limit(lambda: Config.RATE_LIMIT)
def chat():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message", "")).strip()

    if not message or len(message) > Config.MAX_MESSAGE_LEN:
        return jsonify(error="invalid message"), 400

    query_vec = embed_query(message)

    faq_hit = match_faq(query_vec, query_text=message)
    if faq_hit:
        current_app.logger.info("faq match id=%s score=%.3f", faq_hit["id"], faq_hit["score"])
        return jsonify(reply=faq_hit["answer"], source="faq")

    chunks = retrieve_context(query_vec, k=Config.RAG_TOP_K, query_text=message)
    prompt = build_prompt(message, chunks)

    try:
        reply = call_gemini(prompt)
        return jsonify(reply=reply, source="rag")
    except QuotaExceededError:
        current_app.logger.warning("gemini quota exceeded, using fallback")
        return jsonify(reply=Config.FALLBACK_MESSAGE, source="fallback")
    except Exception:
        current_app.logger.exception("gemini call failed")
        return jsonify(reply=Config.FALLBACK_MESSAGE, source="fallback")


@chat_bp.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok")
