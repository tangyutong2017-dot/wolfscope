"""Deterministic one-to-one scoring for public-claim extraction."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from wolfscope.cognition.claims import PublicClaim

from .claim_dataset import ClaimDatasetCase, ForbiddenClaim, GoldClaim


IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "role_claim": ("subject", "role", "polarity"),
    "check_claim": ("target", "night", "result"),
    "alignment_claim": ("target", "alignment", "polarity"),
    "stance_claim": ("target", "stance"),
    "vote_intent": ("target", "intent", "conditional"),
    "vote_recommendation": ("target", "conditional"),
}


@dataclass(frozen=True, slots=True)
class ClaimScore:
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 1.0

    @property
    def f1(self) -> float:
        denominator = self.precision + self.recall
        return 2 * self.precision * self.recall / denominator if denominator else 0.0

    def as_dict(self) -> dict[str, int | float]:
        return {
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


@dataclass(frozen=True, slots=True)
class CaseScore:
    case_id: str
    score: ClaimScore
    matched: tuple[tuple[int, int], ...]
    false_positive_indices: tuple[int, ...]
    false_negative_indices: tuple[int, ...]
    forbidden_hits: tuple[tuple[int, int], ...]


def score_case(
    case: ClaimDatasetCase,
    predictions: tuple[PublicClaim, ...],
) -> CaseScore:
    """Find a maximum one-to-one matching between Gold and predictions."""

    adjacency = [
        [
            prediction_index
            for prediction_index, prediction in enumerate(predictions)
            if claims_match(gold, prediction)
        ]
        for gold in case.expected_claims
    ]
    prediction_to_gold: dict[int, int] = {}

    def augment(gold_index: int, visited: set[int]) -> bool:
        for prediction_index in adjacency[gold_index]:
            if prediction_index in visited:
                continue
            visited.add(prediction_index)
            previous_gold = prediction_to_gold.get(prediction_index)
            if previous_gold is None or augment(previous_gold, visited):
                prediction_to_gold[prediction_index] = gold_index
                return True
        return False

    for gold_index in range(len(case.expected_claims)):
        augment(gold_index, set())

    matched = tuple(
        sorted(
            ((gold_index, prediction_index) for prediction_index, gold_index in prediction_to_gold.items()),
        ),
    )
    matched_gold = {gold for gold, _ in matched}
    matched_predictions = {prediction for _, prediction in matched}
    false_positive_indices = tuple(
        index for index in range(len(predictions)) if index not in matched_predictions
    )
    false_negative_indices = tuple(
        index for index in range(len(case.expected_claims)) if index not in matched_gold
    )
    forbidden_hits = tuple(
        (prediction_index, forbidden_index)
        for prediction_index, prediction in enumerate(predictions)
        for forbidden_index, forbidden in enumerate(case.forbidden_claims)
        if forbidden_matches(forbidden, prediction)
    )
    return CaseScore(
        case_id=case.case_id,
        score=ClaimScore(
            true_positive=len(matched),
            false_positive=len(false_positive_indices),
            false_negative=len(false_negative_indices),
        ),
        matched=matched,
        false_positive_indices=false_positive_indices,
        false_negative_indices=false_negative_indices,
        forbidden_hits=forbidden_hits,
    )


def claims_match(gold: GoldClaim, prediction: PublicClaim) -> bool:
    if gold.kind != prediction.kind:
        return False
    for field in IDENTITY_FIELDS[gold.kind]:
        if _value(getattr(gold, field)) != _value(getattr(prediction, field)):
            return False
    if getattr(gold, "conditional", False):
        gold_condition = _normalize(gold.condition or "")
        predicted_condition = _normalize(getattr(prediction, "condition", "") or "")
        if not gold_condition or not predicted_condition:
            return False
        if gold_condition not in predicted_condition and predicted_condition not in gold_condition:
            return False
    return True


def forbidden_matches(forbidden: ForbiddenClaim, prediction: PublicClaim) -> bool:
    if forbidden.kind != prediction.kind:
        return False
    values = forbidden.model_dump(exclude_none=True)
    values.pop("kind", None)
    return all(_value(value) == _value(getattr(prediction, field, None)) for field, value in values.items())


def aggregate_scores(
    cases: Iterable[tuple[ClaimDatasetCase, tuple[PublicClaim, ...], CaseScore]],
) -> dict[str, Any]:
    total = [0, 0, 0]
    by_kind: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    forbidden_hits = 0
    for case, predictions, result in cases:
        total[0] += result.score.true_positive
        total[1] += result.score.false_positive
        total[2] += result.score.false_negative
        forbidden_hits += len(result.forbidden_hits)
        for gold_index, prediction_index in result.matched:
            kind = case.expected_claims[gold_index].kind
            assert kind == predictions[prediction_index].kind
            by_kind[kind][0] += 1
        for prediction_index in result.false_positive_indices:
            by_kind[predictions[prediction_index].kind][1] += 1
        for gold_index in result.false_negative_indices:
            by_kind[case.expected_claims[gold_index].kind][2] += 1
    return {
        "overall": ClaimScore(*total).as_dict(),
        "by_kind": {
            kind: ClaimScore(*counts).as_dict()
            for kind, counts in sorted(by_kind.items())
        },
        "forbidden_hits": forbidden_hits,
    }


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).lower().split()).strip(
        "，。！？；：,.!?;:",
    )


def _value(value: Any) -> Any:
    return getattr(value, "value", value)
