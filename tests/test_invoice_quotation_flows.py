"""
Test suite for invoice and quotation flows with multi-turn slot accumulation,
context memory, OTP thresholds, and confirmation handling.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.agent import run_agent
from app.services.action_executor import execute_pending_action
from app.redis_client import get_session, set_session


@pytest.fixture
def mock_user():
    """Mock user object."""
    return {
        "org_id": "11111111-0000-0000-0000-000000000001",
        "user_id": "uu111111-0000-0000-0000-000000000001",
        "org_name": "Test Jewellers",
        "user_name": "Test User",
        "role": "admin",
        "permissions": ["create_invoice", "create_quotation"]
    }


@pytest.fixture
def mock_phone():
    """Mock phone number."""
    return "+919372860852"


class TestInvoiceCreation:
    """Test invoice creation flows."""

    @pytest.mark.asyncio
    async def test_invoice_creation_slot_accumulation(self, mock_user, mock_phone):
        """Test multi-turn slot accumulation for invoice creation."""
        # Turn 1: User says "create invoice"
        reply, history, patch = await run_agent(
            "create invoice",
            mock_user,
            mock_phone,
            conversation_history=None,
            pending_action=None
        )
        
        # Should ask for customer name and items
        assert "customer" in reply.lower() or "items" in reply.lower()
        assert patch.get("pending_action") is not None
        assert patch["pending_action"]["intent_key"] == "create_sales_invoice"
        assert patch["pending_action"]["stage"] == "collecting"

        # Turn 2: User provides customer name
        pending_action = patch["pending_action"]
        reply, history, patch = await run_agent(
            "Jain Gold Works",
            mock_user,
            mock_phone,
            conversation_history=history,
            pending_action=pending_action
        )
        
        # Should ask for items
        assert "items" in reply.lower()
        assert patch["pending_action"]["fields"].get("customer_name") == "Jain Gold Works"

        # Turn 3: User provides items
        pending_action = patch["pending_action"]
        reply, history, patch = await run_agent(
            "22kt gold chain 60g, 1 piece at 330000",
            mock_user,
            mock_phone,
            conversation_history=history,
            pending_action=pending_action
        )
        
        # Should show confirmation prompt
        assert "confirm" in reply.lower()
        assert patch["pending_action"]["stage"] == "awaiting_confirmation"
        assert "items" in patch["pending_action"]["fields"]

    @pytest.mark.asyncio
    async def test_invoice_with_items_structure(self, mock_user, mock_phone):
        """Test that invoice items have correct structure."""
        # Simulate after items are collected
        pending_action = {
            "intent_key": "create_sales_invoice",
            "stage": "awaiting_confirmation",
            "fields": {
                "customer_id": "cc111111-0000-0000-0000-000000000004",
                "customer_name": "Jain Gold Works",
                "items": [
                    {
                        "description": "22kt gold chain 60g",
                        "qty": 1,
                        "unit_price": 330000.0,
                        "gst": 9900.0,
                        "total": 339900.0
                    }
                ]
            }
        }

        with patch('app.services.action_executor.fetch_one', new_callable=AsyncMock) as mock_fetch:
            with patch('app.services.action_executor.execute', new_callable=AsyncMock):
                with patch('app.services.action_executor.generate_pdf', new_callable=AsyncMock) as mock_pdf:
                    mock_fetch.return_value = {"name": "Jain Gold Works", "city": "Jaipur", "gst_number": "27AAPFU0939J1ZP"}
                    mock_pdf.return_value = b"fake_pdf_bytes"
                    
                    result = await execute_pending_action(pending_action, mock_user)
                    
                    assert result["success"] == True
                    assert "invoice" in result["message"].lower()
                    assert result["pdf_bytes"] is not None


class TestQuotationCreation:
    """Test quotation creation flows."""

    @pytest.mark.asyncio
    async def test_quotation_creation_slot_accumulation(self, mock_user, mock_phone):
        """Test multi-turn slot accumulation for quotation creation."""
        # Turn 1: User says "quote for Sharma"
        reply, history, patch = await run_agent(
            "quote for Sharma",
            mock_user,
            mock_phone,
            conversation_history=None,
            pending_action=None
        )
        
        # Should ask for customer name and items
        assert "customer" in reply.lower() or "items" in reply.lower()
        assert patch.get("pending_action") is not None
        assert patch["pending_action"]["intent_key"] == "generate_price_quotation"

        # Turn 2: User provides customer name
        pending_action = patch["pending_action"]
        reply, history, patch = await run_agent(
            "Sharma Fine Jewels",
            mock_user,
            mock_phone,
            conversation_history=history,
            pending_action=pending_action
        )
        
        # Should ask for items
        assert "items" in reply.lower()

        # Turn 3: User provides items
        pending_action = patch["pending_action"]
        reply, history, patch = await run_agent(
            "22kt gold ring core, 1 piece at 48000",
            mock_user,
            mock_phone,
            conversation_history=history,
            pending_action=pending_action
        )
        
        # Should show confirmation prompt
        assert "confirm" in reply.lower()
        assert patch["pending_action"]["stage"] == "awaiting_confirmation"

    @pytest.mark.asyncio
    async def test_quotation_with_items_structure(self, mock_user, mock_phone):
        """Test that quotation items have correct structure."""
        pending_action = {
            "intent_key": "generate_price_quotation",
            "stage": "awaiting_confirmation",
            "fields": {
                "customer_id": "cc111111-0000-0000-0000-000000000008",
                "customer_name": "Sharma Fine Jewels",
                "items": [
                    {
                        "description": "22kt gold ring core",
                        "qty": 1,
                        "unit_price": 48000.0,
                        "gst": 1440.0,
                        "total": 49440.0
                    }
                ]
            }
        }

        with patch('app.services.action_executor.fetch_one', new_callable=AsyncMock) as mock_fetch:
            with patch('app.services.action_executor.execute', new_callable=AsyncMock):
                with patch('app.services.action_executor.generate_pdf', new_callable=AsyncMock) as mock_pdf:
                    mock_fetch.return_value = {"name": "Sharma Fine Jewels", "city": "Lucknow", "gst_number": "27AAPFU0939J1ZP"}
                    mock_pdf.return_value = b"fake_pdf_bytes"
                    
                    result = await execute_pending_action(pending_action, mock_user)
                    
                    assert result["success"] == True
                    assert "quotation" in result["message"].lower()
                    assert "valid for 3 days" in result["message"].lower()


class TestOTPThreshold:
    """Test OTP threshold handling."""

    @pytest.mark.asyncio
    async def test_otp_threshold_triggers(self, mock_user, mock_phone):
        """Test that OTP is triggered for high-value invoices."""
        pending_action = {
            "intent_key": "create_sales_invoice",
            "stage": "awaiting_confirmation",
            "fields": {
                "customer_id": "cc111111-0000-0000-0000-000000000006",
                "customer_name": "Mehta Enterprises",
                "items": [
                    {
                        "description": "22kt gold necklace 45g",
                        "qty": 1,
                        "unit_price": 230000.0,
                        "gst": 6900.0,
                        "total": 236900.0
                    }
                ]
            }
        }

        with patch('app.services.action_executor.fetch_one', new_callable=AsyncMock) as mock_fetch:
            # Mock workflow with OTP threshold of 50000
            mock_fetch.return_value = {
                "otp_threshold": 50000.0,
                "approval_threshold": 100000.0
            }
            
            result = await execute_pending_action(pending_action, mock_user)
            
            # Should move to OTP stage since amount > threshold
            assert result["stage"] == "awaiting_otp"
            assert "otp" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_otp_verified_execution(self, mock_user, mock_phone):
        """Test that action executes after OTP verification."""
        pending_action = {
            "intent_key": "create_sales_invoice",
            "stage": "awaiting_otp",
            "fields": {
                "customer_id": "cc111111-0000-0000-0000-000000000006",
                "customer_name": "Mehta Enterprises",
                "items": [
                    {
                        "description": "22kt gold necklace 45g",
                        "qty": 1,
                        "unit_price": 230000.0,
                        "gst": 6900.0,
                        "total": 236900.0
                    }
                ]
            }
        }

        with patch('app.services.action_executor.fetch_one', new_callable=AsyncMock) as mock_fetch:
            with patch('app.services.action_executor.execute', new_callable=AsyncMock):
                with patch('app.services.action_executor.generate_pdf', new_callable=AsyncMock) as mock_pdf:
                    mock_fetch.return_value = {"name": "Mehta Enterprises", "city": "Pune", "gst_number": "27AAPFU0939J1ZP"}
                    mock_pdf.return_value = b"fake_pdf_bytes"
                    
                    result = await execute_pending_action(pending_action, mock_user, otp_verified=True)
                    
                    assert result["success"] == True
                    assert "invoice" in result["message"].lower()


class TestContextMemory:
    """Test context memory across turns."""

    @pytest.mark.asyncio
    async def test_context_persists_across_turns(self, mock_user, mock_phone):
        """Test that draft state persists across multiple turns."""
        # Turn 1
        reply, history, patch = await run_agent(
            "create invoice",
            mock_user,
            mock_phone,
            conversation_history=None,
            pending_action=None
        )
        
        pending_action = patch["pending_action"]
        
        # Turn 2
        reply, history, patch = await run_agent(
            "Jain Gold Works",
            mock_user,
            mock_phone,
            conversation_history=history,
            pending_action=pending_action
        )
        
        # Customer name should be preserved
        assert patch["pending_action"]["fields"]["customer_name"] == "Jain Gold Works"
        
        # Turn 3
        pending_action = patch["pending_action"]
        reply, history, patch = await run_agent(
            "22kt gold chain 60g, 1 piece at 330000",
            mock_user,
            mock_phone,
            conversation_history=history,
            pending_action=pending_action
        )
        
        # Both customer and items should be preserved
        assert patch["pending_action"]["fields"]["customer_name"] == "Jain Gold Works"
        assert "items" in patch["pending_action"]["fields"]


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_missing_customer_id(self, mock_user, mock_phone):
        """Test error when customer_id is missing."""
        pending_action = {
            "intent_key": "create_sales_invoice",
            "stage": "awaiting_confirmation",
            "fields": {
                "customer_name": "Jain Gold Works",
                "items": []
            }
        }

        result = await execute_pending_action(pending_action, mock_user)
        
        assert result["success"] == False
        assert "missing" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_missing_items(self, mock_user, mock_phone):
        """Test error when items are missing."""
        pending_action = {
            "intent_key": "create_sales_invoice",
            "stage": "awaiting_confirmation",
            "fields": {
                "customer_id": "cc111111-0000-0000-0000-000000000004",
                "customer_name": "Jain Gold Works",
                "items": []
            }
        }

        result = await execute_pending_action(pending_action, mock_user)
        
        assert result["success"] == False
        assert "items" in result["message"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
