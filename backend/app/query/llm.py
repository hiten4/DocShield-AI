"""LiteLLM wrapper — provider-agnostic. Groq primary, Gemini fallback."""

import logging
import os

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger(__name__)


def _configure_env():
    if settings.groq_api_key:
        os.environ["GROQ_API_KEY"] = settings.groq_api_key
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key


_configure_env()


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=0.5, max=4))
def complete(system: str, user: str, max_tokens: int | None = None) -> str:
    import litellm

    try:
        resp = litellm.completion(
            model=settings.litellm_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens or settings.llm_max_tokens,
            temperature=0.2,
        )
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning("primary LLM failed, trying fallback: %s", e)
        if settings.gemini_api_key:
            resp = litellm.completion(
                model="gemini/gemini-1.5-flash",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens or settings.llm_max_tokens,
                temperature=0.2,
            )
            return resp["choices"][0]["message"]["content"]
        raise
