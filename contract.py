"""
Request / response contract — the stable spine of the system.

The Streamlit UI builds a ChatRequest, the orchestrator returns a ChatResponse.
A future FastAPI back end wraps this same contract (spec:
HGMP-Chatbot-archive / backend-architecture-spec.md). Keeping this stable is
what lets the comparison rig and the production back end share logic.

Breaking changes here → major version bump (SemVer).
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

# Audience: consumer (product pages) vs distributor staff.
AudienceType = Literal["b2c", "b2b"]

# Which layers are active — lets the rig compare a bare model vs the full stack.
#   raw     = no system prompt, no KB, no guardrail   (measure the naked model)
#   harness = system prompt + medical guardrail        (no product KB)
#   full    = system prompt + guardrail + KB retrieval  (production behaviour)
ConfigType = Literal["raw", "harness", "full"]

# Escalation destinations (tiered notification).
RouteType = Literal[
    "qualified-person",   # personal-medical / adverse reaction → human healthcare staff
    "customer-service",   # ordering, pricing, delivery, complaints, out-of-scope
    "account-management", # B2B account terms, credit, bulk pricing
    "sales",              # B2B new distribution / sales enquiries
]


class ChatRequest(BaseModel):
    """What the front end sends to the orchestrator."""

    message: str = Field(..., min_length=1, max_length=4096, description="User's message")
    session_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Opaque session id; auto-generated if omitted",
    )
    audience: AudienceType = Field(default="b2c", description="b2c = customer, b2b = distributor staff")
    config: ConfigType = Field(default="full", description="Active layers: raw | harness | full")


class ChatResponse(BaseModel):
    """What the orchestrator returns to the front end."""

    answer: str = Field(..., description="Bot reply (ROUTE tag already stripped)")
    route: RouteType | None = Field(default=None, description="Escalation destination, or null")
    sources: list[str] = Field(default_factory=list, description="KB doc ids used to ground the answer")
    model_used: str = Field(..., description="LiteLLM provider/model string that generated the reply")
    config: ConfigType = Field(..., description="The config mode that was active (echoed back)")
