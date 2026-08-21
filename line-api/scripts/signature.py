#!/usr/bin/env python3
"""
LINE API skill — webhook signature verification and channel access token JWT.

Standard library only. Two jobs LINE integrations get wrong most often:

  1. Webhook signature  — must be computed over the RAW request body.
     Base64( HMAC-SHA256( channel secret, raw_body ) ) == x-line-signature

  2. Channel access token v2.1 — an RS256 JWT signed with the assertion
     signing key (a JWK, exactly as the LINE Developers Console hands it to
     you). RSA PKCS#1 v1.5 signing is implemented here directly, so no
     third-party crypto package is needed.

CLI
    python scripts/signature.py verify --secret <channel secret> --body-file body.json --signature <sig>
    python scripts/signature.py sign   --secret <channel secret> --body '{"events":[]}'
    python scripts/signature.py jwt    --jwk private.key --channel-id 1234567890 --kid <kid>
    python scripts/signature.py token  --jwk private.key --channel-id 1234567890 --kid <kid>
    python scripts/signature.py stateless --channel-id 1234 --channel-secret <secret>

Docs
    https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/
    https://developers.line.biz/en/docs/messaging-api/generate-json-web-token/
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import load_dotenv, use_utf8_stdout  # noqa: E402

use_utf8_stdout()
load_dotenv()

API_HOST = "https://api.line.me"

# Maximums stated by LINE: JWT assertion 30 minutes, token 30 days.
MAX_JWT_LIFETIME = 30 * 60
MAX_TOKEN_EXP = 30 * 24 * 60 * 60


# --------------------------------------------------------------------------
# 1. webhook signature
# --------------------------------------------------------------------------
def sign_body(channel_secret: str, body: bytes | str) -> str:
    """Return the value LINE would put in the x-line-signature header."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_signature(channel_secret: str, body: bytes | str, signature: str) -> bool:
    """Constant-time comparison of the computed signature and the header value.

    `body` MUST be the raw bytes as received. Re-serialising parsed JSON
    changes whitespace and key order and will never match.
    """
    expected = sign_body(channel_secret, body)
    return hmac.compare_digest(expected, (signature or "").strip())


# --------------------------------------------------------------------------
# 2. RS256 JWT (pure Python, JWK private key)
# --------------------------------------------------------------------------
def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    s = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _jwk_int(jwk: dict, field: str) -> int:
    if field not in jwk:
        raise ValueError(f"assertion signing key is missing the '{field}' property")
    return int.from_bytes(b64url_decode(jwk[field]), "big")


# ASN.1 DigestInfo prefix for SHA-256 (RFC 8017 §9.2 notes)
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _emsa_pkcs1_v15(message: bytes, em_len: int) -> bytes:
    digest = hashlib.sha256(message).digest()
    t = SHA256_DIGEST_INFO + digest
    if em_len < len(t) + 11:
        raise ValueError("RSA key too small for RS256")
    ps = b"\xff" * (em_len - len(t) - 3)
    return b"\x00\x01" + ps + b"\x00" + t


def rs256_sign(message: bytes, jwk: dict) -> bytes:
    """RSASSA-PKCS1-v1_5 signature using the JWK's n/d values."""
    n = _jwk_int(jwk, "n")
    d = _jwk_int(jwk, "d")
    k = (n.bit_length() + 7) // 8
    em = _emsa_pkcs1_v15(message, k)
    signature = pow(int.from_bytes(em, "big"), d, n)
    return signature.to_bytes(k, "big")


def rs256_verify(message: bytes, signature: bytes, jwk: dict) -> bool:
    """Verify with the public half (n/e). Used by the test-suite round trip."""
    n = _jwk_int(jwk, "n")
    e = _jwk_int(jwk, "e")
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    recovered = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    return hmac.compare_digest(recovered, _emsa_pkcs1_v15(message, k))


def make_jwt(jwk: dict, channel_id: str, kid: str | None = None,
             token_exp: int = MAX_TOKEN_EXP, jwt_lifetime: int = MAX_JWT_LIFETIME,
             now: int | None = None) -> str:
    """Build the assertion JWT for POST /oauth2/v2.1/token.

    iss and sub are both the channel ID, aud is https://api.line.me/,
    exp is at most 30 minutes out and token_exp at most 30 days.
    """
    if jwk.get("kty") != "RSA":
        raise ValueError("assertion signing key must have kty=RSA")
    if jwt_lifetime > MAX_JWT_LIFETIME:
        raise ValueError("JWT assertion lifetime must be 30 minutes or less")
    if token_exp > MAX_TOKEN_EXP:
        raise ValueError("token_exp must be 30 days (2592000 seconds) or less")

    kid = kid or jwk.get("kid")
    if not kid:
        raise ValueError("kid is required — get it from the LINE Developers Console")

    now = int(time.time()) if now is None else now
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    payload = {
        "iss": str(channel_id),
        "sub": str(channel_id),
        "aud": "https://api.line.me/",
        "exp": now + jwt_lifetime,
        "token_exp": token_exp,
    }
    signing_input = (
        b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + b64url(json.dumps(payload, separators=(",", ":")).encode())
    ).encode("ascii")
    return signing_input.decode("ascii") + "." + b64url(rs256_sign(signing_input, jwk))


# --------------------------------------------------------------------------
# 3. token endpoints
# --------------------------------------------------------------------------
def _post_form(url: str, form: dict) -> dict:
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {e.code}: {body}")


def issue_token_v21(jwt_assertion: str) -> dict:
    """POST /oauth2/v2.1/token — channel access token with a chosen expiry."""
    return _post_form(API_HOST + "/oauth2/v2.1/token", {
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": jwt_assertion,
    })


def issue_stateless_token(channel_id: str, channel_secret: str) -> dict:
    """POST /oauth2/v3/token — 15-minute token, no issue-count limit."""
    return _post_form(API_HOST + "/oauth2/v3/token", {
        "grant_type": "client_credentials",
        "client_id": str(channel_id),
        "client_secret": channel_secret,
    })


# --------------------------------------------------------------------------
def _load_jwk(path: str) -> dict:
    jwk = json.loads(Path(path).read_text(encoding="utf-8"))
    if "keys" in jwk:  # a JWK Set
        jwk = jwk["keys"][0]
    return jwk


def main() -> int:
    ap = argparse.ArgumentParser(description="LINE webhook signature / channel access token")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sign", help="compute x-line-signature for a body")
    p.add_argument("--secret", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--body")
    g.add_argument("--body-file")

    p = sub.add_parser("verify", help="verify an x-line-signature header")
    p.add_argument("--secret", required=True)
    p.add_argument("--signature", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--body")
    g.add_argument("--body-file")

    p = sub.add_parser("jwt", help="build the assertion JWT (does not call LINE)")
    p.add_argument("--jwk", required=True, help="private assertion signing key (JWK json)")
    p.add_argument("--channel-id", required=True)
    p.add_argument("--kid")
    p.add_argument("--token-exp", type=int, default=MAX_TOKEN_EXP)

    p = sub.add_parser("token", help="issue a channel access token v2.1")
    p.add_argument("--jwk", required=True)
    p.add_argument("--channel-id", required=True)
    p.add_argument("--kid")
    p.add_argument("--token-exp", type=int, default=MAX_TOKEN_EXP)

    p = sub.add_parser("stateless", help="issue a 15-minute stateless channel access token")
    p.add_argument("--channel-id", required=True)
    p.add_argument("--channel-secret", required=True)

    args = ap.parse_args()

    def body_bytes() -> bytes:
        if getattr(args, "body_file", None):
            return Path(args.body_file).read_bytes()
        return args.body.encode("utf-8")

    if args.cmd == "sign":
        print(sign_body(args.secret, body_bytes()))
        return 0

    if args.cmd == "verify":
        ok = verify_signature(args.secret, body_bytes(), args.signature)
        print("VALID" if ok else "INVALID")
        if not ok:
            print("expected:", sign_body(args.secret, body_bytes()))
            print("received:", args.signature.strip())
            print("提示：簽章必須用「原始 request body bytes」計算，不能用 parse 過再 dump 的 JSON。")
        return 0 if ok else 1

    if args.cmd == "jwt":
        print(make_jwt(_load_jwk(args.jwk), args.channel_id, args.kid, args.token_exp))
        return 0

    if args.cmd == "token":
        jwt_assertion = make_jwt(_load_jwk(args.jwk), args.channel_id, args.kid, args.token_exp)
        print(json.dumps(issue_token_v21(jwt_assertion), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "stateless":
        print(json.dumps(issue_stateless_token(args.channel_id, args.channel_secret),
                         ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
