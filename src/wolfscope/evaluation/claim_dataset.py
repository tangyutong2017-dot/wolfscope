"""Schema and validator for the public-claim gold dataset."""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from wolfscope.cognition.claims import (
    ClaimAlignment,
    ClaimPolarity,
    StanceType,
    VoteIntentType,
)
from wolfscope.contracts import StrictModel
from wolfscope.game.types import RoleType


ClaimKind = Literal[
    "role_claim",
    "check_claim",
    "alignment_claim",
    "stance_claim",
    "vote_intent",
    "vote_recommendation",
]


class DatasetSource(StrictModel):
    source_type: Literal["live_api", "scripted_replay", "manual"]
    game_id: str | None = None
    run_id: str | None = None
    note: str | None = None


class GoldClaim(StrictModel):
    """Semantic identity fields; summary is deliberately not annotated."""

    kind: ClaimKind
    supporting_text: str = Field(min_length=1, max_length=80)
    subject: int | None = Field(default=None, ge=1, le=9)
    role: RoleType | None = None
    polarity: ClaimPolarity | None = None
    target: int | None = Field(default=None, ge=1, le=9)
    night: int | None = Field(default=None, ge=1)
    result: ClaimAlignment | None = None
    alignment: ClaimAlignment | None = None
    stance: StanceType | None = None
    intent: VoteIntentType | None = None
    conditional: bool | None = None
    condition: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def required_fields_for_kind(self):
        required = {
            "role_claim": ("subject", "role", "polarity"),
            "check_claim": ("target", "night", "result"),
            "alignment_claim": ("target", "alignment", "polarity"),
            "stance_claim": ("target", "stance"),
            "vote_intent": ("target", "intent", "conditional"),
            "vote_recommendation": ("target", "conditional"),
        }[self.kind]
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.kind} missing fields: {', '.join(missing)}")
        if self.conditional is True and not self.condition:
            raise ValueError("conditional gold claim requires condition")
        if self.conditional is False and self.condition is not None:
            raise ValueError("unconditional gold claim cannot contain condition")
        return self


class ForbiddenClaim(StrictModel):
    """Partial pattern describing a high-risk claim that must not appear."""

    kind: ClaimKind
    subject: int | None = Field(default=None, ge=1, le=9)
    role: RoleType | None = None
    polarity: ClaimPolarity | None = None
    target: int | None = Field(default=None, ge=1, le=9)
    night: int | None = Field(default=None, ge=1)
    result: ClaimAlignment | None = None
    alignment: ClaimAlignment | None = None
    stance: StanceType | None = None
    intent: VoteIntentType | None = None
    conditional: bool | None = None


class ClaimDatasetCase(StrictModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    review_status: Literal["draft", "reviewed"] = "draft"
    source: DatasetSource
    speaker: int = Field(ge=1, le=9)
    day: int = Field(ge=1)
    speech_context: Literal[
        "sheriff_campaign",
        "day_speech",
        "pk_speech",
        "last_words",
    ]
    text: str = Field(min_length=1)
    expected_claims: tuple[GoldClaim, ...] = ()
    forbidden_claims: tuple[ForbiddenClaim, ...] = ()
    tags: tuple[str, ...] = ()
    difficulty: Literal["basic", "boundary", "adversarial"]
    note: str = ""

    @model_validator(mode="after")
    def quoted_text_and_case_rules(self):
        speech = _normalize(self.text)
        for index, claim in enumerate(self.expected_claims):
            if _normalize(claim.supporting_text) not in speech:
                raise ValueError(
                    f"expected_claims[{index}].supporting_text is not in text",
                )
            if claim.condition and _normalize(claim.condition) not in speech:
                raise ValueError(f"expected_claims[{index}].condition is not in text")
            if claim.kind == "check_claim" and claim.night and claim.night > self.day:
                raise ValueError(f"expected_claims[{index}] uses a future night")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must be unique")
        return self


def load_dataset(path: Path) -> tuple[ClaimDatasetCase, ...]:
    cases: list[ClaimDatasetCase] = []
    case_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                case = ClaimDatasetCase.model_validate_json(raw_line)
            except Exception as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            if case.case_id in case_ids:
                raise ValueError(f"{path}:{line_number}: duplicate case_id {case.case_id}")
            case_ids.add(case.case_id)
            cases.append(case)
    if not cases:
        raise ValueError(f"{path}: dataset is empty")
    return tuple(cases)


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).strip("，。！？；：,.!?;:")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate WolfScope claim dataset")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("datasets/claim_extraction/gold_v1.jsonl"),
    )
    args = parser.parse_args()
    cases = load_dataset(args.path)
    summary = {
        "path": str(args.path),
        "cases": len(cases),
        "draft": sum(case.review_status == "draft" for case in cases),
        "reviewed": sum(case.review_status == "reviewed" for case in cases),
        "expected_claims": sum(len(case.expected_claims) for case in cases),
        "forbidden_claims": sum(len(case.forbidden_claims) for case in cases),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
