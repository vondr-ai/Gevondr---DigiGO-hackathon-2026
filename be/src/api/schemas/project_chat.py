from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator


class ProjectChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ProjectChatFilters(BaseModel):
    norms: list[str] | None = None
    document_ids: list[str] | None = None


class ProjectChatStreamRequest(BaseModel):
    messages: list[ProjectChatMessage] = Field(min_length=1)
    filters: ProjectChatFilters | None = None

    @model_validator(mode="after")
    def validate_messages(self) -> "ProjectChatStreamRequest":
        if not self.messages:
            raise ValueError("At least one message is required.")
        if self.messages[-1].role != "user":
            raise ValueError("The final message must be a user message.")
        return self
