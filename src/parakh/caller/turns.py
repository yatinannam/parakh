"""Pure turn-taking state machine for the scripted caller.

The driver steps it every 20 ms. All inputs arrive as arguments: no I/O, no clock
reads. Times are float milliseconds since call start. The driver passes the playback
end of the last loud agent frame (above -45 dBFS) as playback_end_ms, so silent
frames neither keep the agent speaking nor move that end.

Rules:
1. Caller-first: with agent_speaks_first false and no agent audio by
   caller_first_silence_ms, start the first caller turn.
2. WAIT_AGENT -> AGENT_SPEAKING when the agent speaks; no agent audio for
   response_timeout_ms after the wait began gives timeout.
3. In AGENT_SPEAKING a bot_stopped input is latched together with the current
   playback_end_ms. The reply is over when the agent is not speaking and either the
   latch is set or the silence since playback_end_ms reaches end_of_turn_silence_ms.
   The latch clears if playback_end_ms grows past the recorded value (new audio) and
   whenever a caller turn starts.
4. Whenever a caller turn would start but none remains (n_turns or max_turns
   reached), the machine finishes instead.
5. CALLER_SPEAKING -> next state when the clip is fully sent. Agent audio during
   the clip does not interrupt it.
6. On every entry into AGENT_SPEAKING the machine records the reply onset (the
   agent_onset_ms input, else now) and keeps it until it leaves the state. When the
   next turn has a barge_in offset, the agent is speaking and now reaches onset plus
   that offset, the turn starts with barge_in=True. If the reply ends first, the turn
   starts normally with barge_in=False. Turns without a barge-in carry None.
"""

from collections.abc import Sequence
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
    barge_in: bool | None = None


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
        barge_in_ms: Sequence[float | None] = (),
    ) -> None:
        self.n_turns = n_turns
        self.agent_speaks_first = agent_speaks_first
        self.response_timeout_ms = response_timeout_ms
        self.max_turns = max_turns
        self.end_of_turn_silence_ms = end_of_turn_silence_ms
        self.caller_first_silence_ms = caller_first_silence_ms
        self.barge_in_ms = barge_in_ms
        self.state = TurnState.WAIT_AGENT
        self.turns_started = 0
        self.reply_onset_ms = 0.0
        self._wait_start_ms = 0.0
        self._agent_heard = False
        self._bot_stopped_latched = False
        self._latched_end_ms: float | None = None

    def step(
        self,
        now_ms: float,
        *,
        agent_speaking: bool,
        playback_end_ms: float | None,
        bot_stopped: bool,
        caller_done: bool,
        agent_onset_ms: float | None = None,
    ) -> Action:
        before = self.state
        action = self._dispatch(
            now_ms, agent_speaking, playback_end_ms, bot_stopped, caller_done, agent_onset_ms
        )
        if self.state is TurnState.AGENT_SPEAKING and before is not TurnState.AGENT_SPEAKING:
            self.reply_onset_ms = now_ms if agent_onset_ms is None else agent_onset_ms
        return action

    def _dispatch(
        self,
        now_ms: float,
        agent_speaking: bool,
        playback_end_ms: float | None,
        bot_stopped: bool,
        caller_done: bool,
        agent_onset_ms: float | None,
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
            return self._start_turn_or_finish()
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
        if bot_stopped:
            self._bot_stopped_latched = True
            self._latched_end_ms = playback_end_ms
        elif (
            self._bot_stopped_latched
            and playback_end_ms is not None
            and (self._latched_end_ms is None or playback_end_ms > self._latched_end_ms)
        ):
            self._bot_stopped_latched = False
        if agent_speaking:
            return self._barge_in(now_ms)
        silent_long_enough = (
            playback_end_ms is not None and now_ms - playback_end_ms >= self.end_of_turn_silence_ms
        )
        if not (self._bot_stopped_latched or silent_long_enough):
            return _NONE
        return self._start_turn_or_finish()

    def _turn_remains(self) -> bool:
        return self.turns_started < self.n_turns and self.turns_started < self.max_turns

    def _next_barge_in_ms(self) -> float | None:
        i = self.turns_started
        return self.barge_in_ms[i] if i < len(self.barge_in_ms) else None

    def _barge_in(self, now_ms: float) -> Action:
        after = self._next_barge_in_ms()
        if after is None or not self._turn_remains() or now_ms < self.reply_onset_ms + after:
            return _NONE
        return self._start_turn(barge_in=True)

    def _start_turn_or_finish(self) -> Action:
        if self._turn_remains():
            return self._start_turn(
                barge_in=False if self._next_barge_in_ms() is not None else None
            )
        self.state = TurnState.DONE
        return Action("finish")

    def _start_turn(self, *, barge_in: bool | None) -> Action:
        index = self.turns_started
        self.turns_started += 1
        self._bot_stopped_latched = False
        self._latched_end_ms = None
        self.state = TurnState.CALLER_SPEAKING
        return Action("start_turn", index, barge_in=barge_in)
