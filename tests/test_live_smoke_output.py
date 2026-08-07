from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from wolfscope.live_smoke import _emit_result, _terminal_result


class LiveSmokeOutputTests(unittest.TestCase):
    def test_terminal_result_omits_only_large_trace_arrays(self) -> None:
        result = {
            "game_id": "game-1",
            "trace_summary": {"calls": 2},
            "traces": [{"call": 1}],
            "extraction_traces": [{"call": 2}],
        }

        self.assertEqual(
            _terminal_result(result, summary_only=True),
            {
                "game_id": "game-1",
                "trace_summary": {"calls": 2},
            },
        )
        self.assertIs(_terminal_result(result, summary_only=False), result)

    def test_emit_result_writes_complete_json_before_compact_stdout(self) -> None:
        result = {
            "game_id": "game-1",
            "traces": [{"prompt": "完整 trace"}],
            "extraction_traces": [],
        }
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "nested" / "result.json"

            with redirect_stdout(stdout):
                _emit_result(result, output=output, summary_only=True)

            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                result,
            )
        self.assertEqual(json.loads(stdout.getvalue()), {"game_id": "game-1"})
