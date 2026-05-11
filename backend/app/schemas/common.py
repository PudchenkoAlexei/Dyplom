from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IdResponse(BaseModel):
    id: UUID


class MessageResponse(BaseModel):
    message: str


class Timestamped(ORMModel):
    created_at: datetime
    updated_at: datetime

