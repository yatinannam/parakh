"""Pure turn-taking state machine for the scripted caller.

The driver steps it every 20 ms. All inputs arrive as arguments: no I/O, no clock
reads. Times are float milliseconds since call start.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class TurnState(StrEnum):
    WAIT_AGENT = "wait_agent"
    CALLER_SPEAKING = "caller_speaking"
    AGENT_SPEAKING = "agent_speaking"
    DONE = "done"


@dataclass(frozen=True)
class Action:
    kind: Literal["none", "start_turn", "finish", "timeout"]
    turn_index: int | None = None


_NONE = Action("none")


class TurnMachine:
    def __init__(
        self,
        n_turns: int,
        *,
        agent_speaks_first: bool,
        response_timeout_ms: float,
        max_turns: int,
        end_of_turn_silence_ms: float = 800,
        caller_first_silence_ms: float = 1000,
    ) -> None:
        self.n_turns = n_turns
        self.agent_speaks_first = agent_speaks_first
        self.response_timeout_ms = response_timeout_ms
        self.max_turns = max_turns
        self.end_of_turn_silence_ms = end_of_turn_silence_ms
        self.caller_first_silence_ms = caller_first_silence_ms
        self.state = TurnState.WAIT_AGENT
        self.turns_started = 0
        self._wait_start_ms = 0.0
        self._agent_heard = False

    def step(
        self,
        now_ms: float,
        *,
        agent_speaking: bool,
        playback_end_ms: float | None,
        bot_stopped: bool,
        caller_done: bool,
    ) -> Action:
        match self.state:
            case TurnState.DONE:
                return _NONE
            case TurnState.WAIT_AGENT:
                return self._wait_agent(now_ms, agent_speaking, playback_end_ms)
            case TurnState.AGENT_SPEAKING:
                return self._agent_speaking(now_ms, agent_speaking, playback_end_ms, bot_stopped)
            case TurnState.CALLER_SPEAKING:
                if caller_done:
                    if agent_speaking:
                        self.state = TurnState.AGENT_SPEAKING
                    else:
                        self.state = TurnState.WAIT_AGENT
                        self._wait_start_ms = now_ms
                return _NONE

    def _wait_agent(
        self, now_ms: float, agent_speaking: bool, playback_end_ms: float | None
    ) -> Action:
        if agent_speaking:
            self._agent_heard = True
            self.state = TurnState.AGENT_SPEAKING
            return _NONE
        if (
            not self.agent_speaks_first
            and not self._agent_heard
            and playback_end_ms is None
            and self.turns_started == 0
            and now_ms >= self.caller_first_silence_ms
        ):
            return self._start_turn()
        if now_ms - self._wait_start_ms >= self.response_timeout_ms:
            self.state = TurnState.DONE
            return Action("timeout")
        return _NONE

    def _agent_speaking(
        self,
        now_ms: float,
        agent_speaking: bool,
        playback_end_ms: float | None,
        bot_stopped: bool,
    ) -> Action:
        if agent_speaking:
            return _NONE
        silent_long_enough = (
            playback_end_ms is not None and now_ms - playback_end_ms >= self.end_of_turn_silence_ms
        )
        if not (bot_stopped or silent_long_enough):
            return _NONE
        if self.turns_started < self.n_turns and self.turns_started < self.max_turns:
            return self._start_turn()
        self.state = TurnState.DONE
        return Action("finish")

    def _start_turn(self) -> Action:
        index = self.turns_started
        self.turns_started += 1
        self.state = TurnState.CALLER_SPEAKING
        return Action("start_turn", index)
