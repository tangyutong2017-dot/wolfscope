"""Phase-specific Chinese speech length guidance and deterministic hard limits."""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import DecisionTask


@dataclass(frozen=True, slots=True)
class SpeechLimit:
    target_min_chars: int
    target_max_chars: int
    hard_max_chars: int

    def __post_init__(self) -> None:
        if not 0 < self.target_min_chars <= self.target_max_chars <= self.hard_max_chars:
            raise ValueError("speech character limits must be ordered and positive")


@dataclass(frozen=True, slots=True)
class SpeechPolicyResult:
    text: str
    original_chars: int
    final_chars: int
    truncated: bool


class SpeechPolicy:
    """Guide model length softly, then enforce only a deterministic hard ceiling."""

    LIMITS = {
        DecisionTask.SHERIFF_CAMPAIGN: SpeechLimit(160, 220, 280),
        DecisionTask.SPEECH: SpeechLimit(140, 220, 300),
        DecisionTask.PK_SPEECH: SpeechLimit(100, 160, 220),
        DecisionTask.LAST_WORDS: SpeechLimit(120, 200, 260),
        DecisionTask.DEATH_LAST_WORDS: SpeechLimit(80, 150, 200),
    }
    _SENTENCE_ENDINGS = "。！？!?；;"

    @classmethod
    def limit_for(cls, task: DecisionTask) -> SpeechLimit | None:
        return cls.LIMITS.get(task)

    @classmethod
    def enforce(cls, task: DecisionTask, text: str) -> SpeechPolicyResult:
        normalized = text.strip()
        original_chars = len(normalized)
        limit = cls.limit_for(task)
        if limit is None or original_chars <= limit.hard_max_chars:
            return SpeechPolicyResult(
                text=normalized,
                original_chars=original_chars,
                final_chars=original_chars,
                truncated=False,
            )

        prefix = normalized[: limit.hard_max_chars]
        boundary = max(prefix.rfind(mark) for mark in cls._SENTENCE_ENDINGS)
        if boundary + 1 >= int(limit.hard_max_chars * 0.6):
            shortened = prefix[: boundary + 1].rstrip()
        else:
            shortened = prefix[: limit.hard_max_chars - 1].rstrip() + "…"
        return SpeechPolicyResult(
            text=shortened,
            original_chars=original_chars,
            final_chars=len(shortened),
            truncated=True,
        )
