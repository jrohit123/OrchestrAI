"""
telegram_webhook.py — Telegram Bot webhook endpoint.

Register this webhook with Telegram once after deploy:
    curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
         -d "url=https://<your-app>/webhook/telegram" \
         -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
"""
import hmac
import os
from fastapi import APIRouter, Request, Response, Header
from app.config import required
from app.redis_client import get_redis
from app.logging_config import get_context_logger, bind_context

logger = get_context_logger(__name__)
router = APIRouter()

TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")


@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None),
):
    # Verify secret token if configured
    if TELEGRAM_WEBHOOK_SECRET:
        if not hmac.compare_digest(
            x_telegram_bot_api_secret_token or "", TELEGRAM_WEBHOOK_SECRET
        ):
            return Response(status_code=403)

    update = await request.json()

    # Deduplication — same pattern as WhatsApp webhook
    update_id = update.get("update_id")
    if update_id is not None:
        redis = get_redis()
        was_set = await redis.set(f"tg_processed:{update_id}", "1", ex=300, nx=True)
        if not was_set:
            logger.info(f"Duplicate Telegram update_id {update_id} — skipping")
            return {"status": "ok"}

    bind_context(correlation_id_val=str(update_id or ""))

    # Parse message or callback_query
    callback = update.get("callback_query")
    message  = update.get("message") or update.get("edited_message")

    if callback:
        chat_id  = str(callback["message"]["chat"]["id"])
        text     = callback["data"]
        msg_type = "interactive"
    elif message and message.get("text"):
        chat_id  = str(message["chat"]["id"])
        text     = message["text"]
        msg_type = "text"
    else:
        # Unsupported update type (sticker, photo, etc.)
        return {"status": "ok"}

    phone = f"tg:{chat_id}"
    logger.info(f"Telegram message from {phone}: {text[:80]}")

    try:
        from app.routers.webhook import handle_message
        await handle_message(phone=phone, text=text, msg_type=msg_type)
    except Exception as e:
        logger.error(f"Telegram handle_message error: {e}", exc_info=True)
        try:
            from app.services.telegram import send_text
            await send_text(chat_id, "❌ Something went wrong. Please try again.")
        except Exception:
            pass

    return {"status": "ok"}


@router.get("/webhook/telegram/health")
async def telegram_health():
    """Quick check that the Telegram webhook route is live."""
    return {"status": "ok", "channel": "telegram"}
