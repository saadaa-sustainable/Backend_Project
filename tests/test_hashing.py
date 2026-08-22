from __future__ import annotations

from app.utils.hashing import hash_payload


def test_hash_payload_is_deterministic() -> None:
    payload = {"id": "123", "name": "Test Campaign", "spend": "12.34"}
    assert hash_payload(payload) == hash_payload(dict(payload))


def test_hash_payload_ignores_key_order() -> None:
    a = {"id": "123", "name": "Test"}
    b = {"name": "Test", "id": "123"}
    assert hash_payload(a) == hash_payload(b)


def test_hash_payload_differs_on_value_change() -> None:
    a = {"id": "123", "spend": "1.00"}
    b = {"id": "123", "spend": "2.00"}
    assert hash_payload(a) != hash_payload(b)


def test_hash_payload_is_a_sha256_hex_digest() -> None:
    digest = hash_payload({"id": "1"})
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex
