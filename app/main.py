from fastapi import FastAPI

from app.api.routes.generation import router as generation_router
from app.api.routes.health import router as health_router
from app.api.routes.stripe import router as stripe_router
from app.api.routes.stripe import webhook_router
from app.api.routes.usage import router as usage_router

app = FastAPI(title="FlyRank Metering and Billing Engine")

app.include_router(health_router)
app.include_router(generation_router)
app.include_router(usage_router)
app.include_router(stripe_router)
app.include_router(webhook_router)
