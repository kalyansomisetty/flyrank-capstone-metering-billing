import hashlib
import secrets


def generate_api_key() -> str:
    """Generate a high-entropy API key. Show it only at issuance."""
    return f"frk_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    """Return the SHA-256 digest of a randomly generated API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
