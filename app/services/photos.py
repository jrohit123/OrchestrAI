"""Photos people send on WhatsApp, kept in the client's own database.

WhatsApp keeps a photo for about 30 days only, so the chat bot saves its own copy the moment the photo arrives
(Telegram keeps its photos itself, and only a reference to them is stored, so nothing here touches those).

A photo travels through the existing request flow as a plain reference text, the same way a Telegram file id does:

  wa:<media id>   a photo WhatsApp just handed over, not saved yet (only seen between the webhook and keep_whatsapp_photos)
  db:<uuid>       a photo saved in case_photos; it is put on the case when the request is saved (attach)

The numbers (the largest photo, how many per request, how long an unattached photo is kept) are the organisation's
own: orgs.settings -> limits (photo_max_mb, photo_max) and retention (photos_days).
"""

from app.db import execute, fetch_one
from app.logging_config import get_context_logger
from app.services import config_store, whatsapp

logger = get_context_logger(__name__)

WHATSAPP = "wa:"
STORED = "db:"
ALLOWED_TYPES = (
    "image/jpeg",
    "image/png",
    "image/webp",
)  # what a browser can show safely

NOT_SAVED = "photo.failed"
TOO_BIG = "photo.too_big"


def is_stored(ref) -> bool:
    return str(ref).startswith(STORED)


def stored_id(ref) -> str:
    return str(ref)[len(STORED) :]


async def _keep_one(
    user: dict, media_id: str, limit_bytes: int
) -> tuple[str | None, str | None]:
    """(reference, None) when saved, or (None, the message that says why not)."""
    try:
        info = await whatsapp.media_info(media_id)
        mime = (info.get("mime_type") or "").split(";")[0].strip().lower()
        if mime not in ALLOWED_TYPES:
            logger.warning(f"photos: a file of type '{mime}' is not a photo we keep")
            return None, NOT_SAVED
        size = int(info.get("file_size") or 0)
        if size and size > limit_bytes:
            return None, TOO_BIG
        data = await whatsapp.download_media(info["url"])
        if len(data) > limit_bytes:
            return None, TOO_BIG
        row = await fetch_one(
            "INSERT INTO case_photos (org_id, user_id, source, source_ref, mime_type, size_bytes, data) "
            "VALUES ($1, $2, 'whatsapp', $3, $4, $5, $6) RETURNING id",
            user["org_id"],
            user["user_id"],
            media_id,
            mime,
            len(data),
            data,
            source_key=user["source_key"],
        )
        return f"{STORED}{row['id']}", None
    except Exception as e:  # nothing about the person or the photo is logged
        logger.warning(f"photos: a photo could not be kept: {type(e).__name__}")
        return None, NOT_SAVED


async def keep_whatsapp_photos(
    user: dict, refs: list[str]
) -> tuple[list[str], str | None]:
    """Save every photo WhatsApp handed over and give back references that last. References that are already
    ours (or Telegram's) pass through unchanged. The second value is the message to tell the person when some
    photo could not be saved (None when all went well)."""
    conf = await config_store.org_settings(user["source_key"], user["org_id"])
    limit_bytes = config_store.limit_of(conf, "photo_max_mb") * 1024 * 1024
    kept: list[str] = []
    problem: str | None = None
    for ref in refs:
        if not str(ref).startswith(WHATSAPP):
            kept.append(ref)
            continue
        saved, why = await _keep_one(user, str(ref)[len(WHATSAPP) :], limit_bytes)
        if saved:
            kept.append(saved)
        elif why == TOO_BIG or problem is None:
            problem = why
    return kept, problem


async def attach(source_key: str, org_id, case_id, refs: list[str]) -> None:
    """Put saved photos on a case."""
    for ref in refs:
        if is_stored(ref):
            await execute(
                "UPDATE case_photos SET case_id = $1 WHERE id = $2::uuid AND org_id = $3 AND case_id IS NULL",
                case_id,
                stored_id(ref),
                org_id,
                source_key=source_key,
            )


async def fetch(source_key: str, org_id, ref: str) -> tuple[bytes, str] | None:
    """A saved photo and its type, or None."""
    try:
        row = await fetch_one(
            "SELECT data, mime_type FROM case_photos WHERE id = $1::uuid AND org_id = $2",
            stored_id(ref),
            org_id,
            source_key=source_key,
        )
    except Exception as e:
        logger.warning(f"photos: could not read a saved photo: {type(e).__name__}")
        return None
    return (bytes(row["data"]), row["mime_type"]) if row else None
