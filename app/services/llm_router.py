"""
llm_router.py — Centralised multi-provider LLM client with key rotation and fallback.

Provider order:
  1. Gemini  (3 keys, round-robin rotation, gemini-2.5-flash → gemini-2.0-flash → gemini-2.5-flash-lite)
  2. Groq    (1 key, llama-3.1-8b-instant — free tier with daily reset, 128k context)
  3. OpenAI  (1 key, gpt-4o-mini — paid tier)
  4. Cerebras (1 key, gpt-oss-120b — requires payment method after Aug 17, large context)

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
import time
import asyncio
import random
from dataclasses import dataclass, field
from openai import AsyncOpenAI
from app.logging_config import get_context_logger

logger = get_context_logger(__name__)


class AllProvidersFailed(Exception):
    """Raised only when every non-benched provider has been tried."""
    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__("All LLM providers failed")


# Per-provider cooldown registry. Key = stable provider label.
# Value = unix ts before which we must not retry this provider.
_COOLDOWN_UNTIL: dict[str, float] = {}

# How long to bench a provider after each failure class.
_COOLDOWN_SECONDS = {
    "quota":   900.0,   # 429 / RESOURCE_EXHAUSTED — daily or minute quota
    "server":   60.0,   # 5xx
    "timeout":  30.0,
    "auth":    3600.0,  # 401/403 — bad key, don't hammer it
    "other":    15.0,
}

# Fail fast per attempt so the ladder can actually be walked inside one
# user-visible turn. 30s x 9 attempts is not a fallback, it's an outage.
_ATTEMPT_TIMEOUT = 12.0


def _classify(err: Exception) -> str:
    s = str(err).lower()
    if "429" in s or "quota" in s or "resource_exhausted" in s or "rate limit" in s:
        return "quota"
    if "401" in s or "403" in s or "invalid api key" in s or "permission" in s:
        return "auth"
    if "timeout" in s or "timed out" in s or isinstance(err, asyncio.TimeoutError):
        return "timeout"
    if "500" in s or "502" in s or "503" in s or "529" in s or "overloaded" in s:
        return "server"
    if "404" in s or "not found" in s or "does not exist" in s:
        return "model_missing"
    return "other"


def _cooled_down(label: str) -> bool:
    """True if this provider is benched right now."""
    until = _COOLDOWN_UNTIL.get(label, 0.0)
    if until and time.monotonic() < until:
        return True
    _COOLDOWN_UNTIL.pop(label, None)
    return False


def _bench(label: str, kind: str) -> None:
    secs = _COOLDOWN_SECONDS.get(kind, 15.0)
    # jitter so 3 keys benched together don't all wake in the same millisecond
    _COOLDOWN_UNTIL[label] = time.monotonic() + secs * (0.85 + random.random() * 0.3)
    logger.warning(f"LLM provider '{label}' benched for ~{secs:.0f}s ({kind})")


@dataclass
class _Attempt:
    label:   str
    client:  object
    model:   str
    strip:   tuple = field(default=())   # kwargs this provider rejects


def _build_ladder() -> list[_Attempt]:
    """
    Ordered attempt list. Gemini keys are rotated so we don't always start
    at key 1; everything else is fixed priority.
    """
    ladder: list[_Attempt] = []

    if _gemini_clients:
        n = len(_gemini_clients)
        start = next(_gemini_cycle)
        for ki in range(n):
            idx = (start + ki) % n
            for model in GEMINI_MODELS:
                ladder.append(_Attempt(
                    label=f"gemini_k{idx+1}_{model}",
                    client=_gemini_clients[idx],
                    model=model,
                ))

    if _groq_client:
        ladder.append(_Attempt("groq", _groq_client, GROQ_MODEL,
                               strip=("parallel_tool_calls",)))
    if _openai_client:
        ladder.append(_Attempt("openai", _openai_client, OPENAI_MODEL,
                               strip=("parallel_tool_calls",)))
    if _cerebras_client:
        ladder.append(_Attempt("cerebras", _cerebras_client, CEREBRAS_MODEL))
    return ladder


# Providers whose tool/function-calling is not dependable enough to drive
# the agent's tool loop. They remain available for plain-text formatting.
_NO_RELIABLE_TOOLS = {"groq"}

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

GROQ_MODEL = "llama-3.1-8b-instant"

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
    max_tokens: int = 8192,
    temperature: float = 0.1,
    require_tools: bool = False,
) -> object:
    """
    Walk the provider ladder, skipping anything currently benched.

    require_tools=True  → skip providers whose tool-calling is unreliable
                          (set on the agent's main loop; see §2.3).
    Raises AllProvidersFailed if nothing succeeds.
    """
    errors: dict[str, str] = {}

    base_kwargs: dict = dict(
        max_tokens=max_tokens, temperature=temperature, messages=messages
    )
    if tools:
        base_kwargs["tools"] = tools
    if tool_choice:
        base_kwargs["tool_choice"] = tool_choice
        base_kwargs.setdefault("parallel_tool_calls", False)

    ladder = _build_ladder()

    # Pass 1: only providers that are not benched.
    # Pass 2: if literally everything is benched, ignore cooldowns and try
    #         anyway — a stale bench must never turn into a hard outage.
    for pass_no in (1, 2):
        for att in ladder:
            if pass_no == 1 and _cooled_down(att.label):
                errors.setdefault(att.label, "skipped (cooling down)")
                continue
            if require_tools and att.label in _NO_RELIABLE_TOOLS:
                continue

            kwargs = {k: v for k, v in base_kwargs.items() if k not in att.strip}
            try:
                response = await asyncio.wait_for(
                    att.client.chat.completions.create(model=att.model, **kwargs),
                    timeout=_ATTEMPT_TIMEOUT,
                )
                if att.label in _COOLDOWN_UNTIL:
                    _COOLDOWN_UNTIL.pop(att.label, None)
                logger.info(f"LLM success: {att.label} (pass {pass_no})")
                return response

            except Exception as e:
                kind = _classify(e)
                errors[att.label] = f"{kind}: {e}"
                if kind == "model_missing":
                    # This model doesn't exist on this key. Bench it for a long
                    # time — it will never appear — but don't bench the key.
                    _bench(att.label, "auth")
                    continue
                if kind == "quota":
                    # Bench every remaining model on the SAME key too: a quota
                    # ceiling is per-key, not per-model. This is the single
                    # biggest latency win.
                    key_prefix = att.label.rsplit("_", 1)[0]
                    for other in ladder:
                        if other.label.startswith(key_prefix):
                            _bench(other.label, "quota")
                    continue
                _bench(att.label, kind)
                continue

        if pass_no == 1 and any(not _cooled_down(a.label) for a in ladder):
            break   # pass 1 had live options and they all genuinely failed

    raise AllProvidersFailed(errors)
