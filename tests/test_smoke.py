"""
Smoke tests - catch import-time errors before they reach production.
This would have caught AP-05's NameError and ImportError bugs.
"""
import os
import sys
import pkgutil
from pathlib import Path

# Set required environment variables for imports
os.environ.setdefault("ADMIN_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("CEREBRAS_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_TOKEN", "test-key")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-key")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-secret")
os.environ.setdefault("REDIS_URL", "redis://localhost")
os.environ.setdefault("ROUTING_DATABASE_URL", "postgresql://test")
os.environ.setdefault("BREVO_API_KEY", "test-key")


def test_import_all_app_modules():
    """Import every module in app/ to catch NameError/ImportError at import time."""
    app_path = Path(__file__).parent.parent / "app"
    failures = []
    
    for _, module_name, _ in pkgutil.walk_packages([str(app_path)], prefix="app."):
        try:
            __import__(module_name)
        except ImportError as e:
            # Skip missing optional dependencies
            if "simpleeval" in str(e) or "proxies" in str(e):
                continue
            failures.append((module_name, str(e)))
        except TypeError as e:
            # Skip dependency version mismatches (e.g., proxies argument)
            if "proxies" in str(e):
                continue
            failures.append((module_name, str(e)))
        except Exception as e:
            # Skip runtime errors from missing env vars
            if "Missing required env var" in str(e):
                continue
            failures.append((module_name, str(e)))
    
    if failures:
        error_msg = "\n".join(f"  - {name}: {err}" for name, err in failures)
        assert False, f"Failed to import modules:\n{error_msg}"


def test_import_core_modules():
    """Import core modules that should always work."""
    from app.db import (
        fetch_all,
        fetch_one,
        execute,
    )
    from app.redis_client import (
        init_redis,
        get_redis,
    )
    from app.config import required
    assert True


def test_import_query_engine():
    """Test query_engine can be imported."""
    from app.services.query_engine import _safe, SENSITIVE_COLS, execute_query
    assert True
