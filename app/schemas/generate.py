from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: StrictInt = Field(ge=0)
    cached_input_tokens: StrictInt = Field(ge=0)
    output_tokens: StrictInt = Field(ge=0)
    reasoning_tokens: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_token_breakdown(self) -> "GenerateRequest":
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")

        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens cannot exceed output_tokens")

        return self


class GenerateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: StrictInt = Field(ge=0)
    cached_input_tokens: StrictInt = Field(ge=0)
    output_tokens: StrictInt = Field(ge=0)
    reasoning_tokens: StrictInt = Field(ge=0)
    billable_tokens: StrictInt = Field(ge=0)
    cost_micro_units: StrictInt = Field(ge=0)
