from app.schemas.generate import GenerateRequest
from app.services.generation import request_fingerprint


def test_same_request_produces_same_fingerprint() -> None:
    first = GenerateRequest(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=50,
        reasoning_tokens=10,
    )
    second = GenerateRequest(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=50,
        reasoning_tokens=10,
    )

    assert request_fingerprint(first) == request_fingerprint(second)


def test_changed_payload_produces_different_fingerprint() -> None:
    first = GenerateRequest(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=50,
        reasoning_tokens=10,
    )
    second = GenerateRequest(
        input_tokens=101,
        cached_input_tokens=20,
        output_tokens=50,
        reasoning_tokens=10,
    )

    assert request_fingerprint(first) != request_fingerprint(second)


def test_fingerprint_is_sha256_hex() -> None:
    request = GenerateRequest(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=50,
        reasoning_tokens=10,
    )

    fingerprint = request_fingerprint(request)

    assert len(fingerprint) == 64
    assert all(character in "0123456789abcdef" for character in fingerprint)
