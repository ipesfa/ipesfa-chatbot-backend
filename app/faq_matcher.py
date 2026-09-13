"""Match de la pregunta del usuario contra las FAQs fijas por similitud coseno,
con el mismo boost híbrido por palabra clave que rag.py (ver ahí el porqué)."""

import json
import os

import numpy as np

from .config import Config
from .text_utils import fuzzy_matched_tokens, tokenize

_BOOST_PER_TOKEN = 0.15
_BOOST_MAX_TOKENS = 3
_IDF_FULL_WEIGHT_DOC_FREQ = 3
_IDF_MIN_WEIGHT = 0.35

_cache = {"mtime": None, "vectors": None, "ids": None, "faqs_by_id": None}


def _load_faqs_by_id() -> dict:
    if not os.path.exists(Config.FAQS_PATH):
        return {}
    with open(Config.FAQS_PATH, encoding="utf-8") as f:
        faqs = json.load(f)
    return {faq["id"]: faq for faq in faqs}


def _faq_tokens(faq: dict) -> set[str]:
    text = faq["question"] + " " + " ".join(faq.get("alt_questions", []))
    return tokenize(text)


def _reload_if_stale() -> None:
    if not os.path.exists(Config.FAQ_INDEX_PATH) or not os.path.exists(Config.FAQ_IDS_PATH):
        _cache.update(mtime=None, vectors=None, ids=None, faqs_by_id=None)
        return

    mtime = os.path.getmtime(Config.FAQ_INDEX_PATH)
    if mtime == _cache["mtime"]:
        return

    vectors = np.load(Config.FAQ_INDEX_PATH)["vectors"]
    with open(Config.FAQ_IDS_PATH, encoding="utf-8") as f:
        ids = json.load(f)

    if len(ids) != vectors.shape[0]:
        # Índice a medio escribir o corrupto: no lo usamos, no rompemos la request.
        return

    faqs_by_id = _load_faqs_by_id()
    faq_tokens_by_id = {faq_id: _faq_tokens(faq) for faq_id, faq in faqs_by_id.items()}

    doc_freq: dict[str, int] = {}
    for tokens in faq_tokens_by_id.values():
        for token in tokens:
            doc_freq[token] = doc_freq.get(token, 0) + 1

    _cache.update(
        mtime=mtime,
        vectors=vectors,
        ids=ids,
        faqs_by_id=faqs_by_id,
        faq_tokens_by_id=faq_tokens_by_id,
        doc_freq=doc_freq,
    )


def _token_weight(token: str, doc_freq: dict[str, int]) -> float:
    freq = doc_freq.get(token, 1)
    return max(_IDF_MIN_WEIGHT, min(1.0, _IDF_FULL_WEIGHT_DOC_FREQ / freq))


def match_faq(query_vec: np.ndarray, query_text: str = "") -> dict | None:
    _reload_if_stale()
    vectors, ids, faqs_by_id = _cache["vectors"], _cache["ids"], _cache["faqs_by_id"]

    if vectors is None or vectors.shape[0] == 0:
        return None

    scores = vectors @ query_vec

    # El puntaje semántico solo, en frases cortas, no es confiable con este
    # modelo: "hola" (sin relación) dio 0.635 de similitud cruda contra una
    # FAQ — más alto que un match real como "consejo" vs "Consejo Directivo"
    # (0.384). Por eso una FAQ solo es candidata si comparte al menos una
    # palabra clave real con la pregunta; el score semántico decide EL CUÁL
    # entre candidatas, no SI hay que responder por FAQ.
    query_tokens = tokenize(query_text) if query_text else set()
    if not query_tokens:
        return None

    faq_tokens_by_id = _cache["faq_tokens_by_id"]
    doc_freq = _cache["doc_freq"]
    eligible = np.zeros(len(ids), dtype=bool)

    for i, faq_id in enumerate(ids):
        matched = fuzzy_matched_tokens(query_tokens, faq_tokens_by_id.get(faq_id, set()))
        if not matched:
            continue
        eligible[i] = True
        weight = sum(_token_weight(t, doc_freq) for t in matched)
        scores[i] += _BOOST_PER_TOKEN * min(weight, _BOOST_MAX_TOKENS)

    if not eligible.any():
        return None

    scores = np.where(eligible, scores, -np.inf)
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])

    if best_score < Config.FAQ_SIMILARITY_THRESHOLD:
        return None

    faq_id = ids[best_idx]
    faq = faqs_by_id.get(faq_id)
    if not faq:
        return None

    return {"id": faq_id, "answer": faq["answer"], "score": best_score}
