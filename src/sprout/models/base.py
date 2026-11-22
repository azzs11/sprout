"""Shared base class for every Sprout model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Immutable, strict model: unknown fields are errors."""

    model_config = ConfigDict(frozen=True, extra="forbid")
