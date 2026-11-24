"""The gate that keeps real recordings on this machine (D10, EC-60).

A real run plays the caller's own voice. The driver may send it only to an agent that has
proved it transcribes locally: the agent's first agent_info must report an stt_model that
starts with "local:". Until then every recorded frame goes out as silence of the same size.
No agent_info within REAL_INFO_TIMEOUT_S of the call starting is a refusal, and so is a
later info that reports a remote model. The URL check (loopback only) happens earlier,
in parakh.transport.ws.check_local_agent_url.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal

import numpy as np

from parakh.audio import PCM

REAL_INFO_TIMEOUT_S = 5.0
LOCAL_STT_PREFIX = "local:"
GateState = Literal["pending", "open", "refused"]
_NS_PER_S = 1_000_000_000


class RealDataGate:
    def __init__(
        self,
        started_ns: int,
        *,
        clock: Callable[[], int] = time.perf_counter_ns,
        timeout_s: float = REAL_INFO_TIMEOUT_S,
    ) -> None:
        self._started = started_ns
        self._clock = clock
        self._timeout_ns = round(timeout_s * _NS_PER_S)
        self._timeout_s = timeout_s
        self._state: GateState = "pending"
        self.reason: str | None = None

    @property
    def warning(self) -> str:
        """The warning for a refusal; empty until the gate refuses."""
        return "" if self.reason is None else f"real data refused: {self.reason}"

    def on_agent_info(self, info: dict[str, Any]) -> None:
        """Open on a local stt_model, refuse otherwise. A refusal is final."""
        if self._state == "refused":
            return
        model = info.get("stt_model")
        if isinstance(model, str) and model.startswith(LOCAL_STT_PREFIX):
            self._state = "open"
            return
        self._state = "refused"
        self.reason = (
            "agent reported no stt_model"
            if model is None
            else f"agent stt_model {model!r} is not local"
        )

    def poll(self) -> GateState:
        """The state now; a pending gate refuses once the info is overdue."""
        if self._state == "pending" and self._clock() - self._started >= self._timeout_ns:
            self._state = "refused"
            self.reason = f"no agent info within {self._timeout_s:.1f} s"
        return self._state

    def guard(self, frame: PCM) -> PCM:
        """The frame itself when the gate is open, else silence of the same size."""
        return frame if self.poll() == "open" else np.zeros_like(frame)
