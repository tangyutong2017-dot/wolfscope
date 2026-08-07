"""Run the public-claim extractor blindly against reviewed Gold cases."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Protocol

from wolfscope.cognition.claims import SpeechClaimExtraction, SpeechExtractionItem
from wolfscope.cognition.extraction import (
    PublicClaimExtractorError,
    validate_extracted_claims,
)
from wolfscope.models.claim_extractor import AgentScopePublicClaimExtractor
from wolfscope.models.config import ModelProfile, model_config_for

from .claim_dataset import ClaimDatasetCase, load_dataset
from .claim_metrics import aggregate_scores, score_case


class BenchmarkExtractor(Protocol):
    async def extract(
        self,
        items: tuple[SpeechExtractionItem, ...],
    ) -> tuple[SpeechClaimExtraction, ...]: ...


async def run_benchmark(
    cases: tuple[ClaimDatasetCase, ...],
    extractor: BenchmarkExtractor,
    *,
    model_name: str,
) -> dict[str, Any]:
    reviewed = tuple(case for case in cases if case.review_status == "reviewed")
    if not reviewed:
        raise ValueError("claim benchmark requires at least one reviewed case")

    scored = []
    details: list[dict[str, Any]] = []
    extraction_failures = 0
    partial_cases = 0
    schema_rejections = 0
    for case in reviewed:
        item = SpeechExtractionItem(
            item_id=case.case_id,
            day=case.day,
            speaker=case.speaker,
            speech_context=case.speech_context,
            text=case.text,
        )
        failure_reason = None
        try:
            outputs = await extractor.extract((item,))
        except PublicClaimExtractorError:
            outputs = ()
            extraction_failures += 1
            failure_reason = "extractor_failure"
        output = next((value for value in outputs if value.item_id == case.case_id), None)
        if output is None:
            predictions = ()
            adapter_rejections = 0
            adapter_reasons: tuple[str, ...] = ()
            if failure_reason is None:
                extraction_failures += 1
                failure_reason = "missing_item"
        else:
            predictions, local_reasons = validate_extracted_claims(item, output.claims)
            adapter_rejections = output.rejected_claims
            adapter_reasons = output.rejection_reasons + local_reasons
            schema_rejections += adapter_rejections + len(local_reasons)
            if adapter_rejections or local_reasons:
                partial_cases += 1

        result = score_case(case, predictions)
        scored.append((case, predictions, result))
        details.append(
            {
                "case_id": case.case_id,
                "score": result.score.as_dict(),
                "predicted_claims": [
                    claim.model_dump(mode="json") for claim in predictions
                ],
                "false_positive_indices": list(result.false_positive_indices),
                "false_negative_claims": [
                    case.expected_claims[index].model_dump(mode="json")
                    for index in result.false_negative_indices
                ],
                "forbidden_hits": [
                    {
                        "prediction_index": prediction_index,
                        "forbidden_index": forbidden_index,
                    }
                    for prediction_index, forbidden_index in result.forbidden_hits
                ],
                "rejected_claims": adapter_rejections + len(local_reasons),
                "rejection_reasons": list(adapter_reasons),
                "failure_reason": failure_reason,
            },
        )

    report = aggregate_scores(scored)
    traces = getattr(extractor, "traces", ())
    report.update(
        {
            "dataset_version": "gold-v1",
            "model": model_name,
            "cases": len(reviewed),
            "extraction_failures": extraction_failures,
            "partial_cases": partial_cases,
            "schema_rejections": schema_rejections,
            "input_tokens": sum(trace.token_usage.input_tokens for trace in traces),
            "output_tokens": sum(trace.token_usage.output_tokens for trace in traces),
            "latency_ms": sum(trace.latency_ms for trace in traces),
            "details": details,
        },
    )
    return report


async def _run_live(path: Path) -> dict[str, Any]:
    cases = load_dataset(path)
    config = model_config_for(ModelProfile.TEST)
    extractor = AgentScopePublicClaimExtractor.from_environment(config)
    return await run_benchmark(cases, extractor, model_name=config.model_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run WolfScope claim benchmark")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("datasets/claim_extraction/gold_v1.jsonl"),
    )
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(_run_live(args.path)),
            ensure_ascii=False,
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
