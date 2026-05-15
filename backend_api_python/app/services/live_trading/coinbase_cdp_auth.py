"""
Coinbase Developer Platform (CDP) JWT for Advanced Trade REST API.

Auth: Authorization: Bearer <JWT>
JWT claims follow Coinbase Advanced Python SDK (ES256, kid, uri in payload).
"""

from __future__ import annotations

import base64
import binascii
import secrets
import time
from typing import Any

import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from app.services.live_trading.base import LiveTradingError

CB_REST_HOST = "api.coinbase.com"
API_PREFIX = "/api/v3/brokerage"


def normalize_cdp_private_key(secret: str) -> str:
    """
    Accept CDP EC private key as:
    - PEM text (-----BEGIN ... PRIVATE KEY-----)
    - Single-line base64 PKCS#8 / SEC1 DER (common export from CDP UI)
    Returns PEM string for jwt.encode / cryptography loaders.
    """
    s = (secret or "").strip()
    if not s:
        raise LiveTradingError("Missing Coinbase CDP private key (secret_key)")

    if "BEGIN" in s and "PRIVATE KEY" in s:
        return s if s.endswith("\n") else s + "\n"

    pad = "=" * (-len(s) % 4)
    try:
        raw = base64.b64decode(s + pad, validate=False)
    except (binascii.Error, ValueError) as e:
        raise LiveTradingError(f"Invalid Coinbase private key (not valid base64): {e}") from e

    key: Any
    try:
        key = serialization.load_der_private_key(raw, password=None, backend=default_backend())
    except Exception:
        try:
            key = serialization.load_pem_private_key(raw, password=None, backend=default_backend())
        except Exception as e2:
            raise LiveTradingError(
                "Invalid Coinbase CDP private key. Paste the full PEM from cloud.coinbase.com, "
                "or the one-line base64 key (ECDSA / ES256). Ed25519 keys are not supported for Advanced Trade REST."
            ) from e2

    pem_b = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem_b.decode("utf-8")


def format_jwt_uri(method: str, request_path: str) -> str:
    """Build the `uri` claim: METHOD host/path (no scheme)."""
    m = str(method or "GET").upper()
    p = str(request_path or "")
    if not p.startswith("/"):
        p = "/" + p
    return f"{m} {CB_REST_HOST}{p}"


def build_rest_jwt(*, uri: str, api_key: str, secret_pem: str) -> str:
    """Signed JWT for one REST call (expires in 120s)."""
    pem = secret_pem if "BEGIN" in secret_pem else normalize_cdp_private_key(secret_pem)
    try:
        private_key = serialization.load_pem_private_key(
            pem.encode("utf-8"), password=None, backend=default_backend()
        )
    except Exception as e:
        raise LiveTradingError(f"Invalid Coinbase private key PEM: {e}") from e

    now = int(time.time())
    payload = {
        "sub": api_key,
        "iss": "cdp",
        "nbf": now,
        "exp": now + 120,
        "uri": uri,
    }
    return jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers={"kid": api_key, "nonce": secrets.token_hex(16)},
    )
