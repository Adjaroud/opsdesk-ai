from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


ShortText = Annotated[str, StringConstraints(min_length=3, max_length=300)]
Category = Literal["vpn", "wifi", "printer", "mfa", "access", "software", "hardware", "security"]


class SearchArgs(StrictModel):
    query: ShortText


class IncidentArgs(StrictModel):
    service: Category


class EmptyArgs(StrictModel):
    pass


class TicketArgs(StrictModel):
    ticket_id: Annotated[str, StringConstraints(pattern=r"^TKT-\d{3,8}$")]


class Draft(StrictModel):
    category: Category
    priority: Literal["P2", "P3", "P4"]
    summary: Annotated[str, StringConstraints(min_length=10, max_length=200)]
    rationale: Annotated[str, StringConstraints(min_length=15, max_length=500)]


class SessionInput(StrictModel):
    employee_id: Annotated[str, StringConstraints(pattern=r"^EMP-\d{3}$")]


class ChatInput(StrictModel):
    message: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class Approval(StrictModel):
    draft_id: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]
    draft: Draft
    approved: Literal[True]


class Answer(StrictModel):
    diagnosis: Annotated[str, StringConstraints(min_length=1, max_length=1500)]
    advice: list[Annotated[str, StringConstraints(min_length=1, max_length=600)]] = Field(max_length=6)
    question: Annotated[str, StringConstraints(max_length=500)]
    source_ids: list[str] = Field(max_length=8)
    evidence_ids: list[str] = Field(max_length=16)
