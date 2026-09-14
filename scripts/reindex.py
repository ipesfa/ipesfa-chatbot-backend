"""Reindexado del contenido del sitio (RAG) y de las FAQs.

Uso: python scripts/reindex.py
Pensado para correr por cron (semanal/quincenal) o a mano durante desarrollo.

Escribe los índices de forma atómica (build en un path temporal + os.replace)
para que ninguna request en curso lea un archivo a medio escribir.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.embeddings import embed_passages, embed_queries  # noqa: E402

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
PER_PAGE = 50


def _parse_json_tolerant(text: str) -> list[dict]:
    """Algunos plugins de WP (ej. wc-shortcodes) emiten PHP warnings antes del
    JSON de la REST API en ciertas páginas, lo que rompe el parseo estricto.
    Nos quedamos con todo desde el primer '[' o '{' en adelante."""
    start = min((i for i in (text.find("["), text.find("{")) if i != -1), default=-1)
    if start == -1:
        raise ValueError(f"No se encontró JSON en la respuesta: {text[:200]!r}")
    return json.loads(text[start:])


def _wp_get(path: str, params: dict) -> list[dict]:
    """Pagina un endpoint de la WP REST API y devuelve todos los items.

    Usa la forma ?rest_route=/wp/v2/... en vez de /wp-json/wp/v2/... — esta
    última depende de que la reescritura de URLs "bonitas" esté funcionando,
    y se confirmó que en dev.ipesfa-ushuaia.edu.ar no lo está (404). La forma
    con query string es igual de oficial/soportada por WP y no depende de eso.
    """
    items: list[dict] = []
    page = 1
    while True:
        resp = requests.get(
            f"{Config.WP_BASE_URL}/",
            params={"rest_route": f"/wp/v2/{path}", **params, "page": page, "per_page": PER_PAGE},
            verify=Config.WP_VERIFY_SSL,
            timeout=20,
        )
        if resp.status_code == 400:
            # WP devuelve 400 "rest_post_invalid_page_number" al pasar la última página.
            break
        resp.raise_for_status()
        batch = _parse_json_tolerant(resp.text)
        if not batch:
            break
        items.extend(batch)
        total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break
        page += 1
    return items


def fetch_pages() -> list[dict]:
    return _wp_get("pages", {"status": "publish"})


def fetch_recent_posts() -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=30 * Config.POSTS_WINDOW_MONTHS)
    return _wp_get("posts", {"status": "publish", "after": since.isoformat()})


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(separator="\n\n", strip=True)
    return text


def chunk_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= CHUNK_SIZE:
            current = candidate
            continue

        if current:
            chunks.append(current)
            overlap = current[-CHUNK_OVERLAP:]
            current = f"{overlap}\n\n{para}" if len(overlap) + len(para) <= CHUNK_SIZE else para
        else:
            # Un párrafo solo ya supera CHUNK_SIZE: lo cortamos duro.
            for i in range(0, len(para), CHUNK_SIZE):
                chunks.append(para[i : i + CHUNK_SIZE])
            current = ""

    if current:
        chunks.append(current)

    return chunks


def build_content_index() -> None:
    print("Descargando páginas...")
    pages = fetch_pages()
    print(f"  {len(pages)} páginas")

    print("Descargando novedades recientes...")
    posts = fetch_recent_posts()
    print(f"  {len(posts)} posts (últimos {Config.POSTS_WINDOW_MONTHS} meses)")

    rows: list[dict] = []
    texts_to_embed: list[str] = []

    for source_type, items in (("page", pages), ("post", posts)):
        for item in items:
            title = html_to_text(item["title"]["rendered"])
            body = html_to_text(item["content"]["rendered"])
            if not body:
                continue

            for idx, chunk in enumerate(chunk_text(body)):
                rows.append(
                    {
                        "chunk_id": f"{source_type}-{item['id']}-{idx}",
                        "source_type": source_type,
                        "wp_id": item["id"],
                        "title": title,
                        "url": item["link"],
                        "chunk_index": idx,
                        "text": chunk,
                        # Fecha de última modificación (no de publicación original):
                        # páginas tipo "Inscripciones 2026" se van editando con el
                        # tiempo, así que "modified" refleja mejor qué tan
                        # actualizada está la info que "date" (creación). Gemini la
                        # usa para juzgar vigencia en vez de asumir o inventar.
                        "date": item.get("modified") or item.get("date", ""),
                    }
                )
                # El título se suma al texto embebido (no al texto guardado/mostrado)
                # porque mucho contenido del sitio es listas de botones/carreras con
                # poca prosa (ej. "INSCRIPCIONES 2026") y el modelo de embeddings las
                # relaciona mal con preguntas en lenguaje natural sin esa pista.
                texts_to_embed.append(f"{title}\n\n{chunk}")

    if not rows:
        print("  Sin contenido para indexar, no se escribe content_index.")
        return

    print(f"Generando embeddings de {len(rows)} chunks...")
    vectors = embed_passages(texts_to_embed)

    _atomic_write_npz(Config.CONTENT_INDEX_PATH, vectors)
    _atomic_write_json(Config.CONTENT_META_PATH, rows)
    print(f"  content_index.npz + content_meta.json escritos ({len(rows)} filas).")


def build_faq_index() -> None:
    if not os.path.exists(Config.FAQS_PATH):
        print("No hay data/faqs.json, se omite el índice de FAQs.")
        return

    with open(Config.FAQS_PATH, encoding="utf-8") as f:
        faqs = json.load(f)

    if not faqs:
        print("data/faqs.json está vacío ([]), se omite el índice de FAQs.")
        return

    texts: list[str] = []
    ids: list[str] = []
    for faq in faqs:
        variants = [faq["question"], *faq.get("alt_questions", [])]
        for variant in variants:
            texts.append(variant)
            ids.append(faq["id"])

    print(f"Generando embeddings de {len(texts)} preguntas/variantes de FAQ...")
    vectors = embed_queries(texts)

    _atomic_write_npz(Config.FAQ_INDEX_PATH, vectors)
    _atomic_write_json(Config.FAQ_IDS_PATH, ids)
    print(f"  faq_index.npz + faq_index_ids.json escritos ({len(ids)} filas, {len(faqs)} FAQs).")


def _atomic_write_npz(path: str, vectors: np.ndarray) -> None:
    # np.savez_compressed le agrega ".npz" al nombre si no termina en ".npz",
    # así que el tmp path tiene que terminar en ".npz" para que coincida con lo escrito.
    tmp_path = f"{path[:-4]}.tmp.npz"
    np.savez_compressed(tmp_path, vectors=vectors)
    os.replace(tmp_path, path)


def _atomic_write_json(path: str, data) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, path)


if __name__ == "__main__":
    if not Config.WP_BASE_URL:
        raise SystemExit("Falta WP_BASE_URL en el entorno/.env")

    os.makedirs(Config.DATA_DIR, exist_ok=True)
    build_content_index()
    build_faq_index()
    print("Reindexado completo.")
    sys.stdout.flush()
    # onnxruntime deja un thread-pool nativo que a veces revienta al cerrar el
    # intérprete (visto en macOS); todo el trabajo ya está escrito en disco,
    # así que salimos directo para no ensuciar los logs del cron con eso.
    os._exit(0)
