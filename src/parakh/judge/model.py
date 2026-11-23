"""The judge's validated scores and the parser for a model reply."""

import json
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

FLAGS = (
    "off_script",
    "wrong_details",
    "no_confirmation",
    "repeated_question",
    "ignored_interruption",
    "language_mismatch",
    "unsafe_or_off_topic",
    "instructions_in_transcript",
)

Score = Annotated[int, Field(ge=1, le=5)]
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class JudgeScores(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    understanding: Score
    language_match: Score
    task_progress: Score
    politeness: Score
    interruption_handling: Score | None
    rationale: str = Field(max_length=600)
    flags: list[str]

    @field_validator("flags")
    @classmethod
    def _known_flags(cls, value: list[str]) -> list[str]:
        return [f for f in value if f in FLAGS]


def parse_scores(text: str, *, has_barge_in: bool) -> JudgeScores:
    """Validate one reply. Raises ValueError (pydantic's ValidationError is one)."""
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    scores = JudgeScores.model_validate(json.loads(body))
    if not has_barge_in:
        return scores.model_copy(update={"interruption_handling": None})
    if scores.interruption_handling is None:
        raise ValueError("interruption_handling is required when the call has a barge-in")
    return scores
