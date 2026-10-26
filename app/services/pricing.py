"""Integer-only usage pricing for simulated AI token counts."""

API_CALL_RATE_MICRO_UNITS = 0
FRESH_INPUT_RATE_PER_MILLION = 1_000_000
CACHED_INPUT_RATE_PER_MILLION = 250_000
OUTPUT_RATE_PER_MILLION = 4_000_000

TOKENS_PER_MILLION = 1_000_000


def calculate_cost_micro_units(
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> int:
    """Calculate the event cost, rounding up once using integer arithmetic."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts cannot be negative.")

    if not 0 <= cached_input_tokens <= input_tokens:
        raise ValueError("Cached input tokens must be between zero and input tokens.")

    fresh_input_tokens = input_tokens - cached_input_tokens

    numerator = (
        fresh_input_tokens * FRESH_INPUT_RATE_PER_MILLION
        + cached_input_tokens * CACHED_INPUT_RATE_PER_MILLION
        + output_tokens * OUTPUT_RATE_PER_MILLION
    )

    return (numerator + TOKENS_PER_MILLION - 1) // TOKENS_PER_MILLION


def calculate_billable_tokens(
    *,
    input_tokens: int,
    output_tokens: int,
) -> int:
    """Count input and output tokens once each; reasoning is included in output."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts cannot be negative.")

    return input_tokens + output_tokens
