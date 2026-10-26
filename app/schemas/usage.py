from datetime import date

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class UsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    billing_month: date
    plan_name: str
    subscription_status: str
    api_calls_used: StrictInt = Field(ge=0)
    api_call_limit: StrictInt = Field(ge=0)
    ai_tokens_used: StrictInt = Field(ge=0)
    ai_token_limit: StrictInt = Field(ge=0)
    cost_micro_units: StrictInt = Field(ge=0)
