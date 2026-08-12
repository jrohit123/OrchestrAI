"""
Structured logging configuration with PII redaction.
Replaces print() calls throughout the codebase.
"""
import logging
import re
from typing import Any, Dict
from contextvars import ContextVar

# Context variables for request-scoped logging
correlation_id: ContextVar[str] = ContextVar('correlation_id', default='')
org_id: ContextVar[str] = ContextVar('org_id', default='')
user_id: ContextVar[str] = ContextVar('user_id', default='')

# PII patterns for redaction
PHONE_PATTERN = re.compile(r'\b\d{10}\b')
EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
SENSITIVE_KEYS = {'otp', 'token', 'password', 'api_key', 'database_url', 'secret', 'credential'}


def redact_pii(data: Any) -> Any:
    """
    Redact PII from log data.
    - Masks phone numbers
    - Masks email addresses
    - Masks values for sensitive keys
    """
    if isinstance(data, str):
        # Redact phone numbers
        data = PHONE_PATTERN.sub('[PHONE_REDACTED]', data)
        # Redact email addresses
        data = EMAIL_PATTERN.sub('[EMAIL_REDACTED]', data)
        return data
    elif isinstance(data, dict):
        return {k: redact_pii(v) if k.lower() not in SENSITIVE_KEYS else '[REDACTED]' for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_pii(item) for item in data]
    return data


class PIIRedactingFormatter(logging.Formatter):
    """Custom formatter that redacts PII from log records."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Redact the message
        record.msg = redact_pii(record.msg)
        
        # Ensure context variables exist (for external library logs)
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = ''
        if not hasattr(record, 'org_id'):
            record.org_id = ''
        if not hasattr(record, 'user_id'):
            record.user_id = ''
        
        # Redact extra fields
        record.correlation_id = redact_pii(record.correlation_id)
        record.org_id = redact_pii(record.org_id)
        record.user_id = redact_pii(record.user_id)
        
        return super().format(record)


def setup_logging():
    """Configure structured logging with PII redaction."""
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Console handler with PII redaction
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # JSON-like format for production
    formatter = PIIRedactingFormatter(
        fmt='%(asctime)s | %(levelname)s | %(name)s | correlation_id=%(correlation_id)s | org_id=%(org_id)s | user_id=%(user_id)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    root_logger.addHandler(console_handler)
    
    # Set specific loggers
    logging.getLogger('uvicorn').setLevel(logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('asyncpg').setLevel(logging.WARNING)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)


def bind_context(correlation_id_val: str = None, org_id_val: str = None, user_id_val: str = None):
    """Bind context variables for the current request."""
    if correlation_id_val:
        correlation_id.set(correlation_id_val)
    if org_id_val:
        org_id.set(org_id_val)
    if user_id_val:
        user_id.set(user_id_val)


class LogAdapter(logging.LoggerAdapter):
    """Logger adapter that automatically includes context variables."""
    
    def process(self, msg: Any, kwargs: Dict) -> tuple:
        extra = kwargs.get('extra', {})
        extra['correlation_id'] = correlation_id.get()
        extra['org_id'] = org_id.get()
        extra['user_id'] = user_id.get()
        kwargs['extra'] = extra
        return msg, kwargs


def get_context_logger(name: str) -> LogAdapter:
    """Get a logger adapter with automatic context binding."""
    logger = get_logger(name)
    return LogAdapter(logger, {})
