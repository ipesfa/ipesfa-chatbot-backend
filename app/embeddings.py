"""Wrapper de fastembed compartido por la app y por scripts/reindex.py.

Un solo lugar para el modelo de embeddings, así indexado y consulta en
tiempo real nunca pueden desalinearse. El modelo (sentence-transformers
paraphrase-multilingual-MiniLM-L12-v2) es simétrico: no usa el esquema de
prefijos query:/passage: de los modelos e5, así que se embebe el texto tal
cual tanto para chunks de contenido como para preguntas.
"""

import numpy as np
from fastembed import TextEmbedding

from .config import Config

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=Config.EMBEDDING_MODEL)
    return _model


def _embed(texts: list[str]) -> np.ndarray:
    # batch_size chico a propósito: en hosting compartido con memoria limitada
    # (confirmado: el proceso murió por OOM al pedirle a fastembed que arme
    # de una un solo batch de ~200 textos, con el default batch_size=256).
    # Un batch más chico mantiene el pico de memoria acotado sin importar
    # cuántos textos se embeban en total.
    vectors = np.array(
        list(_get_model().embed(texts, batch_size=8)), dtype=np.float32
    )
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def embed_passages(texts: list[str]) -> np.ndarray:
    """Para contenido que se guarda en el índice (chunks de páginas)."""
    return _embed(texts)


def embed_queries(texts: list[str]) -> np.ndarray:
    """Para preguntas: tanto la del usuario en tiempo real como las FAQ guardadas."""
    return _embed(texts)


def embed_query(text: str) -> np.ndarray:
    return embed_queries([text])[0]
