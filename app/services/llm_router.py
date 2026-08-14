"""
llm_router.py — Centralised multi-provider LLM client with key rotation and fallback.

Provider order:
  1. Cerebras (1 key, gpt-oss-120b — handles large context better)
  2. Gemini  (3 keys, round-robin rotation, gemini-2.5-flash → gemini-2.0-flash → gemini-2.5-flash-lite)
  3. Groq    (1 key, llama-3.3-70b-versatile — reliable tool-calling, but TPM-limited)
  4. OpenAI  (1 key, gpt-4o-mini — last resort)

Usage:
    from app.services.llm_router import chat_completion

    response = await chat_completion(
        messages=[{"role": "user", "content": "hello"}],
        tools=None,          # optional
        tool_choice=None,    # optional
        max_tokens=4096,
        temperature=0.1,
    )
    # returns openai.types.chat.ChatCompletion (same interface regardless of provider)
"""

import os
import itertools
from openai import AsyncOpenAI
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_BASE_URL   = "https://api.groq.com/openai/v1"

# ── Gemini: up to 3 keys, each gets a client ────────────────────────────────
_gemini_clients: list[AsyncOpenAI] = []
for _env in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
    _key = os.getenv(_env)
    if _key:
        try:
            _gemini_clients.append(AsyncOpenAI(
                api_key=_key,
                base_url=GEMINI_BASE_URL,
                timeout=30.0,
            ))
            logger.info(f"Gemini client registered ({_env})")
        except Exception as e:
            logger.warning(f"Failed to init Gemini client for {_env}: {e}")

# Round-robin iterator over Gemini keys
_gemini_cycle = itertools.cycle(range(len(_gemini_clients))) if _gemini_clients else None
_gemini_index = 0  # track current index for logging

# Models to try on each Gemini key (in order)
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite"]

# ── Groq ─────────────────────────────────────────────────────────────────────
_groq_client: AsyncOpenAI | None = None
_groq_key = os.getenv("GROQ_API_KEY")
if _groq_key:
    try:
        _groq_client = AsyncOpenAI(
            api_key=_groq_key,
            base_url=GROQ_BASE_URL,
            timeout=30.0,
        )
        logger.info("Groq client registered")
    except Exception as e:
        logger.warning(f"Failed to init Groq client: {e}")

GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Cerebras ─────────────────────────────────────────────────────────────────
_cerebras_client: AsyncOpenAI | None = None
_cerebras_key = os.getenv("CEREBRAS_API_KEY")
if _cerebras_key:
    try:
        _cerebras_client = AsyncOpenAI(
            api_key=_cerebras_key,
            base_url="https://api.cerebras.ai/v1",
            timeout=30.0,
        )
        logger.info("Cerebras client registered")
    except Exception as e:
        logger.warning(f"Failed to init Cerebras client: {e}")

CEREBRAS_MODEL = "gpt-oss-120b"

# ── OpenAI (last resort) ─────────────────────────────────────────────────────
_openai_client: AsyncOpenAI | None = None
_openai_key = os.getenv("OPENAI_API_KEY")
if _openai_key:
    try:
        _openai_client = AsyncOpenAI(api_key=_openai_key, timeout=30.0)
        logger.info("OpenAI client registered (last resort)")
    except Exception as e:
        logger.warning(f"Failed to init OpenAI client: {e}")

OPENAI_MODEL = "gpt-4o-mini"


async def chat_completion(
    messages: list,
    tools: list | None = None,
    tool_choice=None,
    max_tokens: int = 4096,
    temperature: float = 0.1,
) -> object:
    """
    Try providers in order: Cerebras → Gemini (all keys/models) → Groq → OpenAI.
    Raises Exception if all providers fail, with a combined error message.
    """
    errors: dict[str, str] = {}

    kwargs: dict = dict(max_tokens=max_tokens, temperature=temperature, messages=messages)
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
        # Cerebras / some providers require this disabled
        kwargs.setdefault("parallel_tool_calls", False)

    # ── 1. Cerebras (handles large context better) ─────────────────────────────
    if _cerebras_client:
        try:
            response = await _cerebras_client.chat.completions.create(
                model=CEREBRAS_MODEL, **kwargs
            )
            logger.info(f"LLM success: Cerebras model={CEREBRAS_MODEL}")
            return response
        except Exception as e:
            errors["cerebras"] = str(e)
            logger.warning(f"Cerebras failed: {e}. Falling back to Gemini...")

    # ── 2. Gemini (rotate keys, try each model per key) ───────────────────────
    if _gemini_clients:
        n_keys = len(_gemini_clients)
        # Start from next key in round-robin
        start_idx = next(_gemini_cycle)
        for ki in range(n_keys):
            idx = (start_idx + ki) % n_keys
            client = _gemini_clients[idx]
            for model in GEMINI_MODELS:
                try:
                    response = await client.chat.completions.create(model=model, **kwargs)
                    logger.info(f"LLM success: Gemini key[{idx+1}] model={model}")
                    return response
                except Exception as e:
                    err_str = str(e)
                    label = f"gemini_key{idx+1}_{model}"
                    errors[label] = err_str
                    # 404 = model not found on this key, try next model
                    # 429 / 503 = quota/rate, skip to next key
                    if "429" in err_str or "503" in err_str or "quota" in err_str.lower():
                        logger.warning(f"Gemini key[{idx+1}] {model} rate-limited, trying next key...")
                        break  # break model loop, try next key
                    elif "404" in err_str:
                        logger.warning(f"Gemini key[{idx+1}] {model} not found, trying next model...")
                        continue  # try next model on same key
                    else:
                        logger.warning(f"Gemini key[{idx+1}] {model} failed: {e}")
                        continue

    # ── 3. Groq (reliable tool-calling, but TPM-limited) ─────────────────────────
    if _groq_client:
        # Groq doesn't support parallel_tool_calls kwarg — strip it
        groq_kwargs = {k: v for k, v in kwargs.items() if k != "parallel_tool_calls"}
        try:
            response = await _groq_client.chat.completions.create(
                model=GROQ_MODEL, **groq_kwargs
            )
            logger.info(f"LLM success: Groq model={GROQ_MODEL}")
            return response
        except Exception as e:
            errors["groq"] = str(e)
            logger.warning(f"Groq failed: {e}. Falling back to OpenAI...")

    # ── 4. OpenAI (last resort) ───────────────────────────────────────────────
    if _openai_client:
        openai_kwargs = {k: v for k, v in kwargs.items() if k != "parallel_tool_calls"}
        try:
            response = await _openai_client.chat.completions.create(
                model=OPENAI_MODEL, **openai_kwargs
            )
            logger.info(f"LLM success: OpenAI model={OPENAI_MODEL}")
            return response
        except Exception as e:
            errors["openai"] = str(e)
            logger.error(f"OpenAI also failed: {e}")

    # All providers exhausted
    error_summary = " | ".join(f"{k}: {v}" for k, v in errors.items())
    raise Exception(f"All LLM providers failed — {error_summary}")
