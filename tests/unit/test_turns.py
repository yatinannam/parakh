from parakh.caller.turns import Action, TurnMachine, TurnState

NONE = Action("none")

# (now_ms, agent_speaking, playback_end_ms, bot_stopped, caller_done)
Inputs = tuple[float, bool, float | None, bool, bool]


def run(machine: TurnMachine, steps: list[Inputs]) -> list[Action]:
    return [
        machine.step(now, agent_speaking=sp, playback_end_ms=pe, bot_stopped=bs, caller_done=cd)
        for now, sp, pe, bs, cd in steps
    ]


def test_agent_first_greeting_then_turn() -> None:
    m = TurnMachine(2, agent_speaks_first=True, response_timeout_ms=8000, max_turns=10)
    out = run(
        m,
        [
            (100, True, 1100, False, False),
            (1000, False, 1100, False, False),
            (1899, False, 1100, False, False),
            (1900, False, 1100, False, False),
        ],
    )
    assert out == [NONE, NONE, NONE, Action("start_turn", 0)]
    assert m.state is TurnState.CALLER_SPEAKING
    assert m.turns_started == 1


def test_bot_stopped_ends_reply_early() -> None:
    m = TurnMachine(2, agent_speaks_first=True, response_timeout_ms=8000, max_turns=10)
    out = run(
        m,
        [
            (100, True, 1100, False, False),
            (1120, False, 1100, False, False),
            (1150, False, 1100, True, False),
        ],
    )
    assert out == [NONE, NONE, Action("start_turn", 0)]


def test_bot_stopped_ignored_while_speaking() -> None:
    m = TurnMachine(2, agent_speaks_first=True, response_timeout_ms=8000, max_turns=10)
    out = run(m, [(100, True, 1100, False, False), (500, True, 1100, True, False)])
    assert out == [NONE, NONE]
    assert m.state is TurnState.AGENT_SPEAKING


def test_pause_inside_reply_is_not_turn_end() -> None:
    m = TurnMachine(2, agent_speaks_first=True, response_timeout_ms=8000, max_turns=10)
    out = run(
        m,
        [
            (0, True, 1000, False, False),
            (1000, False, 1000, False, False),
            (1500, True, 2500, False, False),
            (2500, False, 2500, False, False),
            (3299, False, 2500, False, False),
            (3300, False, 2500, False, False),
        ],
    )
    assert out == [NONE, NONE, NONE, NONE, NONE, Action("start_turn", 0)]


def test_response_timeout() -> None:
    m = TurnMachine(2, agent_speaks_first=False, response_timeout_ms=8000, max_turns=10)
    out = run(
        m,
        [
            (1000, False, None, False, False),
            (5000, False, None, False, True),
            (12999, False, None, False, False),
            (13000, False, None, False, False),
        ],
    )
    assert out == [Action("start_turn", 0), NONE, NONE, Action("timeout")]
    assert m.state is TurnState.DONE
    assert (
        m.step(
            14000, agent_speaking=False, playback_end_ms=None, bot_stopped=False, caller_done=False
        )
        == NONE
    )


def test_finish_after_last_reply() -> None:
    m = TurnMachine(1, agent_speaks_first=True, response_timeout_ms=8000, max_turns=10)
    out = run(
        m,
        [
            (0, True, 500, False, False),
            (1300, False, 500, False, False),
            (1400, False, 500, False, True),
            (2000, True, 3000, False, False),
            (3799, False, 3000, False, False),
            (3800, False, 3000, False, False),
        ],
    )
    assert out == [NONE, Action("start_turn", 0), NONE, NONE, NONE, Action("finish")]
    assert m.state is TurnState.DONE
    assert (
        m.step(
            4000, agent_speaking=False, playback_end_ms=3000, bot_stopped=False, caller_done=False
        )
        == NONE
    )


def test_max_turns_caps_the_script() -> None:
    m = TurnMachine(5, agent_speaks_first=True, response_timeout_ms=8000, max_turns=2)
    out = run(
        m,
        [
            (0, True, 500, False, False),
            (1300, False, 500, False, False),  # start_turn(0)
            (1400, False, 500, False, True),  # caller done -> WAIT_AGENT
            (2000, True, 3000, False, False),
            (3800, False, 3000, False, False),  # start_turn(1)
            (3900, False, 3000, False, True),
            (4000, True, 5000, False, False),
            (5800, False, 5000, False, False),  # finish
        ],
    )
    assert [a for a in out if a.kind != "none"] == [
        Action("start_turn", 0),
        Action("start_turn", 1),
        Action("finish"),
    ]
    assert out[-1] == Action("finish")


def test_caller_first_waits_for_silence() -> None:
    m = TurnMachine(2, agent_speaks_first=False, response_timeout_ms=8000, max_turns=10)
    out = run(m, [(999, False, None, False, False), (1000, False, None, False, False)])
    assert out == [NONE, Action("start_turn", 0)]


def test_caller_first_but_agent_greets() -> None:
    m = TurnMachine(2, agent_speaks_first=False, response_timeout_ms=8000, max_turns=10)
    out = run(
        m,
        [
            (500, True, 1500, False, False),
            (1000, True, 1500, False, False),
            (1500, False, 1500, False, False),
            (2299, False, 1500, False, False),
            (2300, False, 1500, False, False),
        ],
    )
    assert out == [NONE, NONE, NONE, NONE, Action("start_turn", 0)]
