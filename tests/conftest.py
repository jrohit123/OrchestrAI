"""Shared test fixtures. `world` (three throwaway databases) lives in test_migrate.py."""

import os

# The app reads a .env file when it is imported, and what it finds there can be a real database
# address or a real key. A file never overrides what is already set, so harmless values go in
# first: no test can ever hold, or use, a real address.
for _name, _value in {
    "ROUTING_DATABASE_URL": "postgresql://postgres@127.0.0.1:9/none",
    "ADMIN_TOKEN": "test",
    "BREVO_API_KEY": "test",
    "OPENAI_API_KEY": "test",
    "REDIS_URL": "redis://127.0.0.1:9/0",
    "SENDER_EMAIL": "test@example.invalid",
    "SENDER_NAME": "test",
    "TELEGRAM_BOT_TOKEN": "0:test",
    "WHATSAPP_APP_SECRET": "test",
    "WHATSAPP_TOKEN": "test",
    "WHATSAPP_VERIFY_TOKEN": "test",
}.items():
    os.environ[_name] = _value

from tests.test_migrate import world  # noqa: F401
