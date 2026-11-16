"""Estimate free-tier Groq usage of a batch of scenarios before running it."""

from dataclasses import dataclass, field

from parakh.scenario import Scenario

GROQ_STT_LIMITS = {"rpm": 20, "rpd": 2000, "audio_s_per_hour": 7200}
# Assumed, not read from Groq: check the console for the real limits.
GROQ_LLM_ASSUMED = {"rpm": 30, "rpd": 1000}
_SECONDS_PER_WORD = 0.4


@dataclass
class Estimate:
    scenarios: int
    stt_calls: int
    llm_calls: int
    audio_seconds: float
    within_limits: bool
    notes: list[str] = field(default_factory=list)


def estimate(scenarios: list[Scenario], clip_seconds: list[float] | None = None) -> Estimate:
    """STT calls = caller turns; LLM calls = caller turns, plus 1 if the agent speaks first.

    Audio seconds come from clip_seconds when given, else 0.4 s per word of `say`.
    The audio limit is compared with the whole batch, as if it ran within one hour.
    """
    stt = sum(len(s.turns) for s in scenarios)
    llm = stt + sum(1 for s in scenarios if s.agent_speaks_first)
    if clip_seconds is not None:
        audio = float(sum(clip_seconds))
    else:
        audio = _SECONDS_PER_WORD * sum(len(t.say.split()) for s in scenarios for t in s.turns)
    notes: list[str] = []
    if stt > GROQ_STT_LIMITS["rpd"]:
        notes.append(f"rpd: {stt} STT calls > {GROQ_STT_LIMITS['rpd']}")
    if llm > GROQ_LLM_ASSUMED["rpd"]:
        notes.append(f"rpd: {llm} LLM calls > {GROQ_LLM_ASSUMED['rpd']} (assumed limit)")
    if audio > GROQ_STT_LIMITS["audio_s_per_hour"]:
        limit = GROQ_STT_LIMITS["audio_s_per_hour"]
        notes.append(f"audio_s_per_hour: {audio:.0f} s of audio > {limit}")
    return Estimate(len(scenarios), stt, llm, audio, not notes, notes)
