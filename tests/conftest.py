"""
Test fixtures and configuration.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import fakeredis


@pytest.fixture
def mock_redis():
    """Mock Redis client for tests."""
    return fakeredis.aio.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_openai():
    """Mock OpenAI client for tests."""
    from openai import AsyncOpenAI
    
    mock_client = AsyncMock(spec=AsyncOpenAI)
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Test response"
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].finish_reason = "stop"
    
    async def mock_create(*args, **kwargs):
        return mock_response
    
    mock_client.chat.completions.create = mock_create
    return mock_client


@pytest.fixture
def mock_db_pool():
    """Mock database pool for tests."""
    pool = AsyncMock()
    return pool


@pytest.fixture
def sample_org():
    """Sample organization data."""
    return {
        "id": "11111111-0000-0000-0000-000000000001",
        "name": "Test Org",
        "gst_rate": 0.03,
        "session_ttl_minutes": 480,
    }


@pytest.fixture
def sample_user():
    """Sample user data."""
    return {
        "user_id": "3fd62f03-1d08-4ef0-9c76-526b4ae10bc5",
        "org_id": "11111111-0000-0000-0000-000000000001",
        "user_name": "Test User",
        "phone": "+919223315977",
        "role": "owner",
        "role_id": "1",
        "permissions": ["*"],
    }


@pytest.fixture
def sample_workflow():
    """Sample workflow data."""
    return {
        "id": "workflow-123",
        "org_id": "11111111-0000-0000-0000-000000000001",
        "intent_key": "create_invoice",
        "llm_system_prompt": "You are an invoice assistant.",
        "entity_schema": {
            "customer_name": {"type": "string", "required": True},
            "amount": {"type": "number", "required": True},
        },
    }


@pytest.fixture
def mock_whatsapp_send():
    """Mock WhatsApp send function."""
    async def mock_send(to: str, message: str, **kwargs):
        return {"message_id": "test-msg-id"}
    return mock_send


@pytest.fixture
def mock_brevo_send():
    """Mock Brevo email send function."""
    async def mock_send(to: str, subject: str, content: str, **kwargs):
        return {"message_id": "test-email-id"}
    return mock_send
