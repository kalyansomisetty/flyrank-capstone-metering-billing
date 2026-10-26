from pydantic import BaseModel, ConfigDict, Field


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    plan_name: str = Field(min_length=1, max_length=64)


class CheckoutResponse(BaseModel):
    session_id: str
    checkout_url: str
