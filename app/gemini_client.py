from google import genai
from google.genai import errors as genai_errors

from .config import Config


class QuotaExceededError(Exception):
    pass


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=Config.GEMINI_API_KEY)
    return _client


def call_gemini(prompt: str) -> str:
    if Config.FORCE_GEMINI_FAILURE:
        raise QuotaExceededError("FORCE_GEMINI_FAILURE activo")

    try:
        response = _get_client().models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=prompt,
        )
    except genai_errors.ClientError as e:
        code = getattr(e, "code", None)
        if code == 429 or "RESOURCE_EXHAUSTED" in str(e):
            raise QuotaExceededError(str(e)) from e
        raise

    text = (response.text or "").strip()
    if not text:
        raise QuotaExceededError("Respuesta vacía de Gemini")
    return text
