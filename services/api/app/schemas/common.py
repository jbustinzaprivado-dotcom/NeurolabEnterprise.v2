from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Contratos en camelCase, igual que los tipos de `apps/web/src/types`."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)
