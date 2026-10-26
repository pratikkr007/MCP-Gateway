
import base64
import ipaddress
import os
import secrets
import socket
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_encryption_key() -> bytes:
    """Read a base64-encoded, 32-byte AES-256 key."""
    encoded = os.getenv("UPSTREAM_CREDENTIALS_KEY", "").strip()

    if not encoded:
        raise RuntimeError(
            "UPSTREAM_CREDENTIALS_KEY is not configured"
        )

    try:
        key = base64.urlsafe_b64decode(
            encoded + "=" * (-len(encoded) % 4)
        )
    except Exception as exc:
        raise RuntimeError(
            "UPSTREAM_CREDENTIALS_KEY must be valid URL-safe base64"
        ) from exc

    if len(key) != 32:
        raise RuntimeError(
            "UPSTREAM_CREDENTIALS_KEY must decode to exactly 32 bytes"
        )

    return key


def encrypt_credential(value: str) -> tuple[str, str]:
    """Return (ciphertext, nonce), both base64 encoded."""
    if not value:
        raise ValueError("Credential cannot be empty")

    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(_get_encryption_key())

    ciphertext = aesgcm.encrypt(
        nonce,
        value.encode("utf-8"),
        None,
    )

    return (
        base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        base64.urlsafe_b64encode(nonce).decode("ascii"),
    )


def decrypt_credential(
    ciphertext: str | None,
    nonce: str | None,
) -> str | None:
    """Decrypt a stored credential or return None if absent."""
    if not ciphertext or not nonce:
        return None

    try:
        cipher_bytes = base64.urlsafe_b64decode(ciphertext)
        nonce_bytes = base64.urlsafe_b64decode(nonce)

        return AESGCM(_get_encryption_key()).decrypt(
            nonce_bytes,
            cipher_bytes,
            None,
        ).decode("utf-8")
    except Exception as exc:
        raise RuntimeError(
            "Could not decrypt upstream credential. "
            "Check the encryption key and database."
        ) from exc


def build_auth_headers(
    auth_mode: str,
    credential: str | None,
    custom_header_name: str | None = None,
) -> dict[str, str]:
    """Build request headers for one upstream."""
    mode = (auth_mode or "none").lower()

    if mode == "none":
        return {}

    if not credential:
        raise RuntimeError(
            f"Authentication mode '{mode}' requires a credential"
        )

    if mode == "bearer":
        return {"Authorization": f"Bearer {credential}"}

    if mode == "custom_header":
        header_name = (custom_header_name or "").strip()

        if not header_name:
            raise RuntimeError(
                "custom_header mode requires a header name"
            )

        if any(ch in header_name for ch in "\r\n:"):
            raise RuntimeError("Invalid custom header name")

        if any(ch in credential for ch in "\r\n"):
            raise RuntimeError("Invalid custom header credential")

        if header_name.lower() in {
            "host",
            "content-length",
            "transfer-encoding",
            "connection",
        }:
            raise RuntimeError(
                "This HTTP header cannot be used for upstream authentication"
            )

        return {header_name: credential}

    raise RuntimeError(
        f"Unsupported upstream authentication mode: {mode}"
    )


def validate_upstream_url(url: str) -> str:
    """
    Validate upstream URLs.

    UPSTREAM_ALLOWED_HOSTS, when configured, is a comma-separated
    hostname allowlist. Local/private hosts remain available for local
    development unless an allowlist is configured.
    """
    value = url.strip()
    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Upstream URL must use HTTP or HTTPS")

    if not parsed.hostname:
        raise ValueError("Upstream URL must contain a hostname")

    if parsed.username or parsed.password:
        raise ValueError(
            "Do not embed credentials in the upstream URL"
        )

    if parsed.fragment:
        raise ValueError("Upstream URL must not contain a fragment")

    hostname = parsed.hostname.rstrip(".").lower()

    if hostname in {
        "metadata.google.internal",
        "metadata",
    }:
        raise ValueError("This upstream hostname is not permitted")

    allowed_hosts = {
        item.strip().lower().rstrip(".")
        for item in os.getenv(
            "UPSTREAM_ALLOWED_HOSTS", ""
        ).split(",")
        if item.strip()
    }

    if allowed_hosts and hostname not in allowed_hosts:
        raise ValueError(
            "Upstream hostname is not in UPSTREAM_ALLOWED_HOSTS"
        )

    # Explicitly block common cloud metadata IPs.
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_link_local:
            raise ValueError(
                "Link-local upstream addresses are not permitted"
            )
    except ValueError as exc:
        # Re-raise our link-local rejection, but allow ordinary DNS names.
        if "Link-local" in str(exc):
            raise

    return value.rstrip("/")
