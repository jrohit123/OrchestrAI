import os


def required(name: str) -> str:
    """Get a required environment variable. Raises RuntimeError if missing."""
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f'Missing required env var: {name}')
    return val
