import pytest
from pydantic import ValidationError

from app.schemas.generate import GenerateResponse


def test_accepts_valid_response() -> None:
    response = GenerateResponse(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=50,
        reasoning_tokens=10,
        billable_tokens=150,
        cost_micro_units=270,
    )

    assert response.billable_tokens == 150
    assert response.cost_micro_units == 270


def test_rejects_negative_cost() -> None:
    with pytest.raises(ValidationError):
        GenerateResponse(
            input_tokens=100,
            cached_input_tokens=20,
            output_tokens=50,
            reasoning_tokens=10,
            billable_tokens=150,
            cost_micro_units=-1,
        )


def test_rejects_unexpected_fields() -> None:
    with pytest.raises(ValidationError):
        GenerateResponse(
            input_tokens=100,
            cached_input_tokens=20,
            output_tokens=50,
            reasoning_tokens=10,
            billable_tokens=150,
            cost_micro_units=270,
            tenant_id="client-controlled",
        )
