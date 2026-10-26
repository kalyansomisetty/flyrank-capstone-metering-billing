import pytest

from app.services.pricing import (
    calculate_billable_tokens,
    calculate_cost_micro_units,
)


def test_calculates_cost_using_all_token_categories() -> None:
    cost = calculate_cost_micro_units(
        input_tokens=100,
        cached_input_tokens=40,
        output_tokens=20,
    )

    assert cost == 150


def test_cached_input_is_cheaper_than_fresh_input() -> None:
    fresh_cost = calculate_cost_micro_units(
        input_tokens=4,
        cached_input_tokens=0,
        output_tokens=0,
    )
    cached_cost = calculate_cost_micro_units(
        input_tokens=4,
        cached_input_tokens=4,
        output_tokens=0,
    )

    assert fresh_cost == 4
    assert cached_cost == 1


def test_rounds_up_once_using_integer_arithmetic() -> None:
    cost = calculate_cost_micro_units(
        input_tokens=1,
        cached_input_tokens=1,
        output_tokens=1,
    )

    assert cost == 5


def test_reasoning_tokens_are_not_added_twice() -> None:
    # Reasoning tokens are already included in output_tokens.
    assert calculate_billable_tokens(input_tokens=100, output_tokens=50) == 150


@pytest.mark.parametrize(
    ("input_tokens", "cached_input_tokens", "output_tokens"),
    [
        (-1, 0, 0),
        (1, -1, 0),
        (1, 2, 0),
        (1, 0, -1),
    ],
)
def test_rejects_invalid_token_counts(
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> None:
    with pytest.raises(ValueError):
        calculate_cost_micro_units(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
        )
