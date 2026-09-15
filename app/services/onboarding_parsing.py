"""
onboarding_parsing.py — deterministic, regex-only parsing for the Telegram
self-registration/linking flow (webhook.py's "tg:" branch).

These are the CHEAP first pass: run before any LLM fallback, since most real
typed messages ("my email is x@y.com", "the code is 4821") are trivially
extractable without a model call. Nothing here decides pass/fail on anything
security-relevant — OTP correctness is still checked by otp_service.py's
exact hash comparison; these helpers only figure out WHAT candidate value
the user meant to submit.
"""
import re

_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_OTP_DIGITS_RE = re.compile(r"\d{3,8}")

_NAME_FILLER_RE = re.compile(
    r"^(?:hi|hey|hello|yeah|yep|sure|ok|okay)?[,!\.\s]*"
    r"(?:i'?m|im|it'?s|its|my name'?s|my name is|this is|call me|you can call me)\s+",
    re.IGNORECASE,
)

_EDIT_RE = re.compile(
    r"(?:change|update|set|make)\s+(?:my\s+)?(name|email|role)\s+(?:to|as|is)\s+(.+)",
    re.IGNORECASE,
)


def extract_email(text: str) -> str | None:
    """First email-shaped substring anywhere in the message, trailing
    sentence punctuation stripped (people end sentences right after a TLD)."""
    m = _EMAIL_RE.search(text)
    if not m:
        return None
    return m.group(0).strip(".,;:!?()<>\"'")


def extract_otp_candidates(text: str) -> list[str]:
    """Distinct plausible-length digit runs found anywhere in the message,
    in order of appearance. Empty = nothing code-shaped was said; more than
    one = ambiguous. Either case means: don't spend a real verify attempt
    on it, ask again instead."""
    seen: list[str] = []
    for m in _OTP_DIGITS_RE.finditer(text):
        d = m.group(0)
        if d not in seen:
            seen.append(d)
    return seen


def clean_name(text: str) -> str:
    """Strip common leading filler ("my name is", "it's", "call me") from a
    name reply. Leaves trailing chatter alone on purpose — low-risk field,
    shown back at the confirm step so the user can correct it there."""
    cleaned = _NAME_FILLER_RE.sub("", text.strip(), count=1).strip()
    return cleaned or text.strip()


def parse_edit_command(text: str) -> tuple[str, str] | None:
    """Matches explicit 'change/set/make <field> to <value>' phrasing.
    Returns (field, value) with field in {"name","email","role"}, or None
    if the message isn't in that shape — callers should fall back to the
    LLM parser for freer phrasing ("wait its actually X", "no make it Y")."""
    m = _EDIT_RE.search(text.strip())
    if not m:
        return None
    field = m.group(1).lower()
    value = m.group(2).strip().strip(".,;:!?\"'")
    if not value:
        return None
    return field, value


def resolve_role_by_text(text: str, options: list[dict]) -> dict | None:
    """Digit index, exact name, or unambiguous substring match against the
    role list. Returns None (not a guess) when nothing is a confident match
    — callers should fall back to the LLM mapper for free-text answers like
    "I own my flat here", since role names are per-org/dynamic and can't be
    covered by a fixed keyword list."""
    choice = text.strip()
    if choice.isdigit() and 1 <= int(choice) <= len(options):
        return options[int(choice) - 1]

    low = choice.lower()
    exact = next((o for o in options if o["name"].lower() == low), None)
    if exact:
        return exact

    contains = [o for o in options if o["name"].lower() in low or low in o["name"].lower()]
    if len(contains) == 1:
        return contains[0]
    return None
