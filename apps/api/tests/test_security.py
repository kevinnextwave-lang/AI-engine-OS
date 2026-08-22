import uuid

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_password_hash_is_argon2id_and_verifies() -> None:
    h = hash_password("s3cret-password")
    assert h.startswith("$argon2id$")
    assert verify_password("s3cret-password", h)
    assert not verify_password("wrong", h)
    assert not verify_password("s3cret-password", "not-a-hash")


def test_access_token_round_trip() -> None:
    uid = uuid.uuid4()
    token = create_access_token(uid)
    payload = decode_access_token(token)
    assert payload["sub"] == str(uid)
    assert payload["type"] == "access"


def test_expired_access_token_rejected() -> None:
    token = create_access_token(uuid.uuid4(), expires_minutes=-1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_token_with_wrong_type_rejected() -> None:
    s = get_settings()
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "iat": 0, "exp": 4102444800},
        s.jwt_secret_key,
        algorithm=s.jwt_algorithm,
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(forged)


def test_token_signed_with_other_key_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": 0, "exp": 4102444800},
        "another-secret-key-that-is-long-enough",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(forged)


def test_refresh_tokens_are_unique_and_hash_is_stable() -> None:
    a, b = generate_refresh_token(), generate_refresh_token()
    assert a != b
    assert len(a) >= 48
    assert hash_token(a) == hash_token(a)
    assert hash_token(a) != hash_token(b)
