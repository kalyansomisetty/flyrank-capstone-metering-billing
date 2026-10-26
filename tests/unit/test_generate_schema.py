import pytest
from pydantic import ValidationError

from app.schemas.generate import GenerateRequest


def test_accepts_valid_token_breakdown() -> None:
    request = GenerateRequest(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=50,
        reasoning_tokens=10,
    )

    assert request.input_tokens == 100
    assert request.cached_input_tokens == 20
    assert request.output_tokens == 50
    assert request.reasoning_tokens == 10


@pytest.mark.parametrize(
    "payload",
    [
        {
            "input_tokens": -1,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        },
        {
            "input_tokens": 5,
            "cached_input_tokens": 6,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        },
        {
            "input_tokens": 5,
            "cached_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_tokens": 6,
        },
        {
            "input_tokens": 5,
            "cached_input_tokens": 0,
            "output_tokens": -1,
            "reasoning_tokens": 0,
        },
    ],
)
def test_rejects_invalid_token_breakdown(payload: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        GenerateRequest(**payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_tokens", "100"),
        ("input_tokens", 10.5),
        ("input_tokens", True),
        ("cached_input_tokens", "20"),
        ("output_tokens", 50.5),
        ("reasoning_tokens", False),
    ],
)
def test_rejects_non_integer_token_counts(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "output_tokens": 50,
        "reasoning_tokens": 10,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        GenerateRequest(**payload)


def test_rejects_unexpected_fields() -> None:
    with pytest.raises(ValidationError):
        GenerateRequest(
            input_tokens=1,
            cached_input_tokens=0,
            output_tokens=1,
            reasoning_tokens=0,
            tenant_id="someone-else",
        )
