"""Recuperación de los chunks de contenido más relevantes para una consulta."""

import json
import os
from datetime import date

import numpy as np

from .config import Config
from .text_utils import fuzzy_matched_tokens, tokenize

_cache = {"mtime": None, "vectors": None, "meta": None, "title_doc_freq": None}

# Boost por coincidencia de palabras con el título del chunk: mucho contenido
# del sitio es listas de botones/carreras (ej. "INSCRIPCIONES 2026") con poca
# prosa, donde el puro parecido semántico no alcanza para ganarle a una página
# más "redactada" pero menos relevante (ej. una edición vieja del mismo trámite).
# Coincidencias literales de palabras clave (fechas, nombres propios) son una
# señal fuerte que el embedding solo no captura bien.
_TITLE_BOOST_PER_TOKEN = 0.15
_TITLE_BOOST_MAX_TOKENS = 3

# Palabras que aparecen en el título de muchos chunks (ej. "Actuales", que es
# el título literal de varios chunks de una página de investigaciones) pesan
# menos: si no, cualquier pregunta que las contenga empuja esas páginas al
# tope aunque no tengan nada que ver. doc_freq<=3 -> peso completo; de ahí
# para arriba, se escala hacia abajo, pero con un piso: palabras como
# "taller" aparecen en decenas de posts distintos PORQUE hay decenas de
# talleres reales (no es ruido), así que igual necesitan aportar algo.
_IDF_FULL_WEIGHT_DOC_FREQ = 3
_IDF_MIN_WEIGHT = 0.35


def _reload_if_stale() -> None:
    if not os.path.exists(Config.CONTENT_INDEX_PATH) or not os.path.exists(Config.CONTENT_META_PATH):
        _cache.update(mtime=None, vectors=None, meta=None)
        return

    mtime = os.path.getmtime(Config.CONTENT_INDEX_PATH)
    if mtime == _cache["mtime"]:
        return

    vectors = np.load(Config.CONTENT_INDEX_PATH)["vectors"]
    with open(Config.CONTENT_META_PATH, encoding="utf-8") as f:
        meta = json.load(f)

    if len(meta) != vectors.shape[0]:
        # Índice a medio escribir o corrupto: RAG queda no disponible esta request.
        return

    # Categorías/tags de WP se suman al título para el boost: muchos posts
    # reales no dicen "taller"/"capacitación" en el título (ej. "Teledetección
    # e imágenes satelitales...") pero SÍ están categorizados como
    # Capacitación/Cursos — sin esto, esas preguntas genéricas de sección no
    # encuentran nada porque no hay ninguna palabra en común con el título.
    title_tokens_per_row = [
        tokenize(f"{m['title']} {m.get('categories', '')}") for m in meta
    ]
    title_doc_freq: dict[str, int] = {}
    for tokens in title_tokens_per_row:
        for token in tokens:
            title_doc_freq[token] = title_doc_freq.get(token, 0) + 1

    _cache.update(
        mtime=mtime,
        vectors=vectors,
        meta=meta,
        title_doc_freq=title_doc_freq,
        title_tokens_per_row=title_tokens_per_row,
    )


def _token_weight(token: str, title_doc_freq: dict[str, int]) -> float:
    doc_freq = title_doc_freq.get(token, 1)
    return max(_IDF_MIN_WEIGHT, min(1.0, _IDF_FULL_WEIGHT_DOC_FREQ / doc_freq))


def retrieve_context(query_vec: np.ndarray, k: int, query_text: str = "") -> list[dict]:
    _reload_if_stale()
    vectors, meta = _cache["vectors"], _cache["meta"]

    if vectors is None or vectors.shape[0] == 0:
        return []

    scores = vectors @ query_vec

    query_tokens = tokenize(query_text) if query_text else set()
    if query_tokens:
        title_doc_freq = _cache["title_doc_freq"]
        title_tokens_per_row = _cache["title_tokens_per_row"]
        for i in range(len(meta)):
            matched = fuzzy_matched_tokens(query_tokens, title_tokens_per_row[i])
            if not matched:
                continue
            weight = sum(_token_weight(t, title_doc_freq) for t in matched)
            scores[i] += _TITLE_BOOST_PER_TOKEN * min(weight, _TITLE_BOOST_MAX_TOKENS)

    top_idx = np.argsort(-scores)[:k]
    return [
        {**meta[i], "score": float(scores[i])}
        for i in top_idx
    ]


def build_prompt(message: str, chunks: list[dict]) -> str:
    if not chunks:
        context = "(sin contenido relevante encontrado)"
    else:
        context = "\n\n".join(
            f"[Fuente: {c['title']}"
            + (f" — actualizado {c['date'][:10]}" if c.get("date") else "")
            + f" — {c['url']}]\n{c['text']}"
            for c in chunks
        )

    return f"""Sos el asistente virtual del sitio del IPESFA (Instituto Provincial de \
Educación Superior «Florentino Ameghino», Ushuaia). Respondé SIEMPRE en español \
argentino (rioplatense): usá "vos" en vez de "tú" (ej. "podés", "tenés", "escribí"), \
nunca uses conjugaciones de "tú" ni vocabulario de España. Respondé de forma \
breve y clara, usando ÚNICAMENTE la información del CONTEXTO de abajo.

Hoy es {date.today().isoformat()}. Si el contexto incluye fechas, usalas para juzgar \
si algo (un taller, una convocatoria, una inscripción) sigue vigente o ya pasó, y \
aclaralo en la respuesta en vez de ignorarlo.

Si el contexto no alcanza para responder, decilo explícitamente y pedile que \
intente reformular la pregunta con otras palabras o de forma más específica \
(puede que la búsqueda no haya encontrado el contenido correcto, no \
necesariamente que no exista). No tenés memoria de mensajes anteriores, así \
que en esa misma respuesta agregá también que si reformulando tampoco \
encuentra lo que busca, puede escribir a administracion@ipesfa-ushuaia.edu.ar. \
Nunca inventes datos (horarios, fechas, requisitos) que no estén en el contexto.

CONTEXTO:
{context}

PREGUNTA DEL USUARIO:
{message}
"""
