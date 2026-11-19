from datetime import timedelta
from pathlib import Path

import pytest

from parakh.scenario import ScenarioError, load_scenario

EXAMPLE = Path(__file__).resolve().parents[2] / "scenarios/hinglish/clinic-book-hinglish-01.yaml"


def _write(tmp_path: Path, text: str | bytes, name: str = "s.yaml") -> Path:
    d = tmp_path / "dir with space"
    d.mkdir()
    p = d / name
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_text(text, encoding="utf-8")
    return p


def _example_text() -> str:
    return EXAMPLE.read_text(encoding="utf-8")


def test_example_scenario_loads():
    s = load_scenario(EXAMPLE)
    assert s.id == "clinic-book-hinglish-01"
    assert len(s.turns) == 4
    assert s.turns[1].reference == s.turns[1].say
    assert s.turns[2].reference == "haan mera number hai 9845012345"
    assert s.clock.utcoffset() == timedelta(hours=5, minutes=30)
    assert s.limits.response_timeout_s == 8


def test_rejects_unknown_field(tmp_path):
    p = _write(tmp_path, _example_text() + "turnz: []\n", "bad-field.yaml")
    with pytest.raises(ScenarioError) as e:
        load_scenario(p)
    assert "turnz" in str(e.value)
    assert "bad-field.yaml" in str(e.value)


def test_rejects_naive_clock(tmp_path):
    text = _example_text().replace("2026-11-19T10:00:00+05:30", "2026-11-19T10:00:00")
    with pytest.raises(ScenarioError, match="timezone"):
        load_scenario(_write(tmp_path, text))


def test_rejects_empty_turns(tmp_path):
    head = _example_text().split("turns:")[0]
    with pytest.raises(ScenarioError):
        load_scenario(_write(tmp_path, head + "turns: []\n"))


def test_rejects_bad_id(tmp_path):
    text = _example_text().replace("id: clinic-book-hinglish-01", 'id: "Has Space"')
    with pytest.raises(ScenarioError, match="id"):
        load_scenario(_write(tmp_path, text))


def test_bom_and_crlf_accepted(tmp_path):
    raw = _example_text().replace("\n", "\r\n").encode("utf-8")
    s = load_scenario(_write(tmp_path, b"\xef\xbb\xbf" + raw))
    assert s.id == "clinic-book-hinglish-01"


def test_non_utf8_rejected(tmp_path):
    with pytest.raises(ScenarioError, match="UTF-8"):
        load_scenario(_write(tmp_path, b"id: caf\x96\n"))


def test_barge_in_parsed(tmp_path):
    text = _example_text().replace(
        '  - say: "Kal subah, agar possible ho toh saadhe das baje."\n',
        '  - say: "Kal subah, agar possible ho toh saadhe das baje."\n'
        "    barge_in: {after_agent_ms: 1200}\n",
    )
    s = load_scenario(_write(tmp_path, text))
    barge = s.turns[1].barge_in
    assert barge is not None
    assert barge.after_agent_ms == 1200


_LIMITS = "limits: { max_turns: 12, response_timeout_s: 8, call_timeout_s: 180 }"


@pytest.mark.parametrize(
    ("limits", "field"),
    [
        # max_turns 0 played no turn and reported completed with exit 0: a false pass.
        ("limits: { max_turns: 0 }", "max_turns"),
        ("limits: { max_turns: -1 }", "max_turns"),
        # A zero timeout ended the call at once.
        ("limits: { response_timeout_s: 0 }", "response_timeout_s"),
        ("limits: { response_timeout_s: -2 }", "response_timeout_s"),
        ("limits: { call_timeout_s: 0 }", "call_timeout_s"),
        ("limits: { call_timeout_s: -1.5 }", "call_timeout_s"),
        # The driver turns timeouts into integer nanoseconds; infinity overflows.
        ("limits: { call_timeout_s: .inf }", "call_timeout_s"),
        ("limits: { response_timeout_s: .nan }", "response_timeout_s"),
    ],
)
def test_rejects_out_of_range_limits(tmp_path, limits, field):
    text = _example_text()
    assert _LIMITS in text
    with pytest.raises(ScenarioError, match=field):
        load_scenario(_write(tmp_path, text.replace(_LIMITS, limits)))


def test_smallest_valid_limits_accepted(tmp_path):
    limits = "limits: { max_turns: 1, response_timeout_s: 0.1, call_timeout_s: 0.1 }"
    s = load_scenario(_write(tmp_path, _example_text().replace(_LIMITS, limits)))
    assert s.limits.max_turns == 1


@pytest.mark.parametrize(("after_ms", "ok"), [(-1, False), (0, True)])
def test_barge_in_offset_not_negative(tmp_path, after_ms, ok):
    text = _example_text().replace(
        '  - say: "Kal subah, agar possible ho toh saadhe das baje."\n',
        '  - say: "Kal subah, agar possible ho toh saadhe das baje."\n'
        f"    barge_in: {{after_agent_ms: {after_ms}}}\n",
    )
    path = _write(tmp_path, text)
    if ok:
        barge = load_scenario(path).turns[1].barge_in
        assert barge is not None and barge.after_agent_ms == 0
    else:
        with pytest.raises(ScenarioError, match="after_agent_ms"):
            load_scenario(path)


def test_barge_in_on_first_turn_needs_agent_first(tmp_path):
    text = _example_text().replace("agent_speaks_first: true", "agent_speaks_first: false")
    first = '  - say: "Hello, mujhe Dr. Rao ke saath follow-up appointment chahiye."\n'
    assert first in text
    text = text.replace(first, first + "    barge_in: {after_agent_ms: 100}\n")
    with pytest.raises(ScenarioError, match="barge_in on the first turn needs agent_speaks_first"):
        load_scenario(_write(tmp_path, text))
