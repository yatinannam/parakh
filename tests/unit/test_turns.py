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


def test_bot_stopped_latched_until_playback_ends() -> None:
    m = TurnMachine(2, agent_speaks_first=True, response_timeout_ms=8000, max_turns=10)
    out = run(
        m,
        [
            (100, True, 1100, False, False),
            (900, True, 1100, True, False),
            (1099, True, 1100, False, False),
            (1100, False, 1100, False, False),
        ],
    )
    assert out == [NONE, NONE, NONE, Action("start_turn", 0)]


def test_bot_stopped_latch_cleared_by_new_audio() -> None:
    m = TurnMachine(2, agent_speaks_first=True, response_timeout_ms=8000, max_turns=10)
    out = run(
        m,
        [
            (100, True, 1100, False, False),
            (900, True, 1100, True, False),
            (1000, True, 2000, False, False),
            (2000, False, 2000, False, False),
            (2799, False, 2000, False, False),
            (2800, False, 2000, False, False),
        ],
    )
    assert out == [NONE, NONE, NONE, NONE, NONE, Action("start_turn", 0)]


def test_no_turns_caller_first_finishes() -> None:
    m = TurnMachine(0, agent_speaks_first=False, response_timeout_ms=8000, max_turns=10)
    out = run(m, [(999, False, None, False, False), (1000, False, None, False, False)])
    assert out == [NONE, Action("finish")]
    assert m.turns_started == 0
    assert m.state is TurnState.DONE


def test_max_turns_zero_agent_first_finishes() -> None:
    m = TurnMachine(3, agent_speaks_first=True, response_timeout_ms=8000, max_turns=0)
    out = run(
        m,
        [
            (100, True, 1100, False, False),
            (1899, False, 1100, False, False),
            (1900, False, 1100, False, False),
        ],
    )
    assert out == [NONE, NONE, Action("finish")]
    assert m.turns_started == 0


def test_max_turns_zero_caller_first_finishes() -> None:
    m = TurnMachine(3, agent_speaks_first=False, response_timeout_ms=8000, max_turns=0)
    out = run(m, [(1000, False, None, False, False)])
    assert out == [Action("finish")]


def test_no_turns_agent_first_finishes() -> None:
    m = TurnMachine(0, agent_speaks_first=True, response_timeout_ms=8000, max_turns=10)
    out = run(m, [(100, True, 1100, False, False), (1900, False, 1100, False, False)])
    assert out == [NONE, Action("finish")]


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


def _barge_machine(after_ms: float | None = 1200) -> TurnMachine:
    return TurnMachine(
        3,
        agent_speaks_first=True,
        response_timeout_ms=8000,
        max_turns=10,
        barge_in_ms=[None, after_ms],
    )


def _step(
    m: TurnMachine,
    now: float,
    speaking: bool,
    end: float,
    onset: float | None,
    *,
    done: bool = False,
) -> Action:
    return m.step(
        now,
        agent_speaking=speaking,
        playback_end_ms=end,
        bot_stopped=False,
        caller_done=done,
        agent_onset_ms=onset,
    )


def _reply_begins(m: TurnMachine, reply_ms: float, end_ms: float) -> None:
    """Greeting, caller turn 0, then the reply to it starts at reply_ms."""
    assert _step(m, 0, True, 500, 0) == NONE
    assert _step(m, 1300, False, 500, 0) == Action("start_turn", 0)
    assert _step(m, 1400, False, 500, None, done=True) == NONE
    assert _step(m, reply_ms, True, end_ms, reply_ms) == NONE  # enters AGENT_SPEAKING


def test_barge_in_fires_after_onset() -> None:
    m = _barge_machine()
    _reply_begins(m, 2000, 9000)
    assert _step(m, 3199, True, 9000, 2000) == NONE
    assert _step(m, 3200, True, 9000, 2000) == Action("start_turn", 1, barge_in=True)


def test_barge_in_counts_from_reply_onset() -> None:
    m = _barge_machine()
    _reply_begins(m, 2000, 9000)
    assert _step(m, 2100, True, 9000, 2800) == NONE  # the clock onset moved; ours did not
    assert _step(m, 3199, True, 9000, 2800) == NONE
    assert _step(m, 3200, True, 9000, 2800) == Action("start_turn", 1, barge_in=True)


def test_barge_in_missed_when_reply_ends_first() -> None:
    m = _barge_machine()
    _reply_begins(m, 2000, 2500)
    assert _step(m, 3200, False, 2500, 2000) == NONE
    assert _step(m, 3299, False, 2500, 2000) == NONE
    assert _step(m, 3300, False, 2500, 2000) == Action("start_turn", 1, barge_in=False)


def test_barge_in_on_greeting() -> None:
    m = TurnMachine(
        2,
        agent_speaks_first=True,
        response_timeout_ms=8000,
        max_turns=10,
        barge_in_ms=[500],
    )
    assert _step(m, 100, True, 3000, 100) == NONE
    assert _step(m, 599, True, 3000, 100) == NONE
    assert _step(m, 600, True, 3000, 100) == Action("start_turn", 0, barge_in=True)


def test_turn_without_barge_in_has_none() -> None:
    m = _barge_machine()
    assert _step(m, 0, True, 500, 0) == NONE
    assert _step(m, 1300, False, 500, 0) == Action("start_turn", 0, barge_in=None)


def test_second_barge_in_waits_after_caller_turn() -> None:
    m = TurnMachine(
        3,
        agent_speaks_first=True,
        response_timeout_ms=8000,
        max_turns=10,
        barge_in_ms=[1000, 1000],
    )
    # The agent speaks from t=0 and never stops: agent_onset_ms stays 0.
    assert _step(m, 0, True, 100, 0) == NONE
    assert _step(m, 980, True, 1000, 0) == NONE
    assert _step(m, 1000, True, 1020, 0) == Action("start_turn", 0, barge_in=True)
    assert _step(m, 2000, True, 2020, 0) == NONE
    assert _step(m, 3000, True, 3020, 0, done=True) == NONE  # clip ends; agent still speaking
    assert m.reply_onset_ms == 3000
    for now in range(3020, 4000, 20):
        assert _step(m, now, True, now + 20, 0) == NONE
    assert _step(m, 4000, True, 4020, 0) == Action("start_turn", 1, barge_in=True)
