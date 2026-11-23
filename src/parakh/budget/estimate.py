"""Estimate free-tier Groq usage of a batch of scenarios before running it."""

from dataclasses import dataclass, field

from parakh.judge.providers import load_config
from parakh.scenario import Scenario

GROQ_STT_LIMITS = {"rpm": 20, "rpd": 2000, "audio_s_per_hour": 7200}
# Assumed, not read from Groq: check the console for the real limits.
GROQ_LLM_ASSUMED = {"rpm": 30, "rpd": 1000, "tpd": 200_000}
# Assumed until Task 9 measures the mean tokens per agent LLM request.
LLM_TOKENS_PER_REQUEST = 1500
_SECONDS_PER_WORD = 0.4
# Observed per caller turn in the M1 runs (the agent's VAD can split one turn into several).
STT_PER_TURN = 3
LLM_PER_TURN = 3


def judge_rpd() -> int:
    """Daily request limit of the first judge provider, from judge.yaml."""
    return load_config().providers[0].rpd


@dataclass
class Estimate:
    scenarios: int
    stt_calls: int
    llm_calls: int
    llm_tokens: int
    judge_calls: int
    audio_seconds: float
    within_limits: bool
    notes: list[str] = field(default_factory=list)


def estimate(
    scenarios: list[Scenario],
    clip_seconds: list[float] | None = None,
    presets: int = 1,
    judge: bool = True,
) -> Estimate:
    """STT calls = 3 per caller turn; LLM calls = 3 per turn, plus 1 if the agent speaks first.

    Agent LLM tokens = LLM calls * LLM_TOKENS_PER_REQUEST. The judge adds one call per run.

    Everything is multiplied by presets (one run per scenario per preset).

    Audio seconds come from clip_seconds when given, else 0.4 s per word of `say`.
    The audio limit is compared with the whole batch, as if it ran within one hour.
    """
    turns = sum(len(s.turns) for s in scenarios)
    stt = STT_PER_TURN * turns * presets
    greetings = sum(1 for s in scenarios if s.agent_speaks_first)
    llm = (LLM_PER_TURN * turns + greetings) * presets
    if clip_seconds is not None:
        audio = float(sum(clip_seconds))
    else:
        audio = _SECONDS_PER_WORD * sum(len(t.say.split()) for s in scenarios for t in s.turns)
    audio *= presets
    tokens = llm * LLM_TOKENS_PER_REQUEST
    judge_calls = len(scenarios) * presets if judge else 0
    notes: list[str] = []
    if stt > GROQ_STT_LIMITS["rpd"]:
        notes.append(f"rpd: {stt} STT calls > {GROQ_STT_LIMITS['rpd']}")
    if llm > GROQ_LLM_ASSUMED["rpd"]:
        notes.append(f"rpd: {llm} LLM calls > {GROQ_LLM_ASSUMED['rpd']} (assumed limit)")
    if tokens > GROQ_LLM_ASSUMED["tpd"]:
        notes.append(f"tpd: {tokens} LLM tokens > {GROQ_LLM_ASSUMED['tpd']} (assumed limit)")
    if judge_calls > judge_rpd():
        notes.append(f"rpd: {judge_calls} judge calls > {judge_rpd()} (judge.yaml limit)")
    if audio > GROQ_STT_LIMITS["audio_s_per_hour"]:
        limit = GROQ_STT_LIMITS["audio_s_per_hour"]
        notes.append(f"audio_s_per_hour: {audio:.0f} s of audio > {limit}")
    return Estimate(len(scenarios), stt, llm, tokens, judge_calls, audio, not notes, notes)
