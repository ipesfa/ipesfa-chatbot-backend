"""Tokenización + stemming crudo compartido por rag.py y faq_matcher.py
para el boost por palabra clave (búsqueda híbrida semántica + keyword)."""

import re
import unicodedata
from difflib import SequenceMatcher

# Tolerancia a errores de tipeo chicos (ej. "incribir" vs "inscribir") al
# comparar tokens para el boost/gate por keyword — sin esto, un typo de una
# sola letra rompe el match por completo (los stems dejan de coincidir).
FUZZY_MATCH_THRESHOLD = 0.8

# Truncar a un prefijo es un "stemmer" muy crudo para español: sin esto,
# "consejeros" en la pregunta no matchea "Consejo" en el título/FAQ (son
# tokens distintos), y preguntas por variantes morfológicas (consejo/
# consejero/consejeros, carrera/carreras) no se benefician del boost.
STEM_PREFIX_LEN = 5

STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a",
    "en", "y", "o", "u", "que", "es", "son", "por", "para", "con", "sobre", "se",
    "su", "sus", "lo", "le", "les", "como", "cual", "cuales", "cuando", "donde",
    "que", "cuanto", "cuanta", "tiene", "tienen", "hay", "este", "esta", "estos",
    "estas", "ese", "esa", "esos", "esas", "mi", "tu", "me", "te", "nos",
    "quien", "quienes", "algun", "alguna", "algunos", "algunas", "puedo", "puedas",
    "pueda", "puede", "pueden", "poder", "hacer",
}


def stem(token: str) -> str:
    return token[:STEM_PREFIX_LEN] if len(token) > STEM_PREFIX_LEN else token


# Sinónimos de dominio: palabras coloquiales que un usuario real usa pero que
# no coinciden con el vocabulario de categorías de WP del sitio (ej. la gente
# dice "taller", pero los posts están categorizados "Capacitación"/"Cursos",
# nunca literalmente "Taller"). Se expande DESPUÉS de tokenizar/stemear, así
# que aplica tanto a la pregunta del usuario como al título/categorías del
# contenido por igual.
SYNONYM_EXPANSIONS: dict[str, list[str]] = {
    "talle": ["capac", "curso"],  # taller/talleres -> Capacitación/Cursos
}


def tokenize(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+", normalized)
    tokens = {stem(w) for w in words if w not in STOPWORDS}
    for token in list(tokens):
        tokens.update(SYNONYM_EXPANSIONS.get(token, []))
    return tokens


def fuzzy_matched_tokens(query_tokens: set[str], target_tokens: set[str]) -> set[str]:
    """Como `query_tokens & target_tokens`, pero además cuenta como match un
    token que sea muy parecido (no exacto) a alguno del otro lado — para que
    un typo de tipeo no rompa el boost/gate por keyword."""
    matched = set()
    for qt in query_tokens:
        if qt in target_tokens:
            matched.add(qt)
            continue
        for tt in target_tokens:
            if SequenceMatcher(None, qt, tt).ratio() >= FUZZY_MATCH_THRESHOLD:
                matched.add(qt)
                break
    return matched
