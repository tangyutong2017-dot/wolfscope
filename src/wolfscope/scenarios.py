"""Small deterministic M1 acceptance scenarios."""

from __future__ import annotations

from .game.night import WitchAction
from .scripted import DayScript, DeathScript, NightScript, ScriptedGame, SheriffScript


GOOD_WIN_SEED_42 = ScriptedGame(
    game_id="good-win-seed-42",
    seed=42,
    max_days=3,
    nights={
        1: NightScript(
            wolf_target=2,
            seer_target=5,
            witch_action=WitchAction.pass_night(),
        ),
        2: NightScript(
            wolf_target=7,
            seer_target=7,
            witch_action=WitchAction.pass_night(),
        ),
    },
    sheriff=SheriffScript(),
    days={
        1: DayScript(
            votes={
                1: 5,
                3: 5,
                4: 5,
                5: 7,
                6: 5,
                7: 5,
                8: 5,
                9: 5,
            },
            last_words={5: "5号被放逐，留下测试遗言"},
        ),
    },
    deaths=DeathScript(
        night_last_words={(1, 2): "2号首夜死亡，留下测试遗言"},
    ),
)


WOLVES_ELIMINATE_DEITIES_SEED_42 = ScriptedGame(
    game_id="wolves-eliminate-deities-seed-42",
    seed=42,
    max_days=4,
    nights={
        1: NightScript(1, 2, WitchAction.pass_night()),
        2: NightScript(6, 5, None),
        3: NightScript(9, 7, None),
    },
    sheriff=SheriffScript(),
    days={
        1: DayScript(votes={seat: None for seat in (2, 3, 4, 5, 6, 7, 8, 9)}),
        2: DayScript(votes={seat: None for seat in (2, 3, 4, 5, 7, 8, 9)}),
    },
    deaths=DeathScript(
        night_last_words={(1, 1): "1号女巫首夜出局"},
        hunter_targets={(2, 6): None},
    ),
)


WOLVES_ELIMINATE_CIVILIANS_SEED_42 = ScriptedGame(
    game_id="wolves-eliminate-civilians-seed-42",
    seed=42,
    max_days=4,
    nights={
        1: NightScript(3, 2, WitchAction.pass_night()),
        2: NightScript(4, 5, WitchAction.pass_night()),
        3: NightScript(8, 7, WitchAction.pass_night()),
    },
    sheriff=SheriffScript(),
    days={
        1: DayScript(votes={seat: None for seat in (1, 2, 4, 5, 6, 7, 8, 9)}),
        2: DayScript(votes={seat: None for seat in (1, 2, 5, 6, 7, 8, 9)}),
    },
    deaths=DeathScript(
        night_last_words={(1, 3): "3号平民首夜出局"},
    ),
)


HUNTER_TIE_BREAK_SEED_42 = ScriptedGame(
    game_id="hunter-tie-break-seed-42",
    seed=42,
    max_days=5,
    nights={
        1: NightScript(1, 2, WitchAction.pass_night()),
        2: NightScript(9, 5, None),
        3: NightScript(3, None, None),
        4: NightScript(6, None, None),
    },
    sheriff=SheriffScript(),
    days={
        1: DayScript(
            votes={seat: (5 if seat == 2 else 2) for seat in (2, 3, 4, 5, 6, 7, 8, 9)},
            last_words={2: "2号狼人被放逐"},
        ),
        2: DayScript(
            votes={seat: (4 if seat == 5 else 5) for seat in (3, 4, 5, 6, 7, 8)},
            last_words={5: "5号狼人被放逐"},
        ),
        3: DayScript(
            votes={seat: (7 if seat == 4 else 4) for seat in (4, 6, 7, 8)},
            last_words={4: "4号平民被放逐"},
        ),
    },
    deaths=DeathScript(
        night_last_words={(1, 1): "1号女巫首夜出局"},
        hunter_targets={(4, 6): 7},
    ),
)


M1_SCENARIOS = {
    scenario.game_id: scenario
    for scenario in (
        GOOD_WIN_SEED_42,
        WOLVES_ELIMINATE_DEITIES_SEED_42,
        WOLVES_ELIMINATE_CIVILIANS_SEED_42,
        HUNTER_TIE_BREAK_SEED_42,
    )
}
