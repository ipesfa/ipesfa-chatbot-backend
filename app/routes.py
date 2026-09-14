from flask import Blueprint, current_app, jsonify, request

from .config import Config
from .embeddings import embed_query
from .faq_matcher import match_faq
from .gemini_client import QuotaExceededError, call_gemini
from .rag import NO_CONTEXT_SENTINEL, build_prompt, retrieve_context
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
    if faq_hit and not faq_hit["fallback_only"]:
        current_app.logger.info("faq match id=%s score=%.3f", faq_hit["id"], faq_hit["score"])
        return jsonify(reply=faq_hit["answer"], source="faq")

    chunks = retrieve_context(query_vec, k=Config.RAG_TOP_K, query_text=message)
    # Si hay una FAQ fallback_only disponible (ej. "Capacitación" — navegación
    # genérica porque la página real está vacía en la API de WP), le pedimos a
    # Gemini una señal exacta y parseable cuando no encuentra nada, en vez de
    # adivinar por el texto de su respuesta (un umbral de score de RAG
    # resultó poco confiable: preguntas vagas a veces rankean alto con
    # contenido igual de irrelevante).
    prompt = build_prompt(message, chunks, has_fallback=bool(faq_hit))

    try:
        reply = call_gemini(prompt)
        if faq_hit and reply.strip() == NO_CONTEXT_SENTINEL:
            current_app.logger.info("faq fallback_only id=%s (gemini sin contexto)", faq_hit["id"])
            return jsonify(reply=faq_hit["answer"], source="faq")
        return jsonify(reply=reply, source="rag")
    except QuotaExceededError:
        current_app.logger.warning("gemini quota exceeded, using fallback")
        return jsonify(
            reply=(faq_hit["answer"] if faq_hit else Config.FALLBACK_MESSAGE),
            source=("faq" if faq_hit else "fallback"),
        )
    except Exception:
        current_app.logger.exception("gemini call failed")
        return jsonify(
            reply=(faq_hit["answer"] if faq_hit else Config.FALLBACK_MESSAGE),
            source=("faq" if faq_hit else "fallback"),
        )


@chat_bp.route("/health", methods=["GET"])
def health():
    return jsonify(status="ok")
