import warnings
from types import SimpleNamespace
from typing import Any

import pytest
from pipecat.frames.frames import EndFrame, Frame, InterruptionWorkerFrame, LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_response_universal import (
    LLMAssistantAggregator,
    LLMUserAggregator,
)
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frameworks.rtvi import RTVIProcessor, RTVIServerMessageFrame
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.groq.stt import GroqSTTService

from agents.clinic_agent.config import load_config
from agents.clinic_agent.tts_edge import EdgeTTSService

# Pipecat's websocket transport touches a websockets API that is deprecated upstream. The
# warning fires at import and at transport construction; ignore exactly that message.
_WS = r"websockets\.(WebSocketServerProtocol|legacy) is deprecated"
pytestmark = pytest.mark.filterwarnings(f"ignore:{_WS}:DeprecationWarning")
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=_WS, category=DeprecationWarning)
    from agents.clinic_agent import bot


class _SpyPipeline(Pipeline):
    last: "_SpyPipeline | None" = None

    def __init__(self, processors: list[Any], **kwargs: Any) -> None:
        super().__init__(processors, **kwargs)
        self.listed = list(processors)
        _SpyPipeline.last = self


def _handler(obj: Any, name: str) -> Any:
    handlers = obj._event_handlers[name].handlers
    assert len(handlers) == 1
    return handlers[0]


def _spy_frames(task: Any, monkeypatch: pytest.MonkeyPatch) -> list[Frame]:
    seen: list[Frame] = []

    async def queue_frame(frame: Frame, *_args: Any, **_kwargs: Any) -> None:
        seen.append(frame)

    async def queue_frames(frames: Any, *_args: Any, **_kwargs: Any) -> None:
        seen.extend(frames)

    monkeypatch.setattr(task, "queue_frame", queue_frame)
    monkeypatch.setattr(task, "queue_frames", queue_frames)
    return seen


def test_pipeline_order_and_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "Pipeline", _SpyPipeline)
    _task, transport = bot.build_task(load_config(), "test-key")
    assert _SpyPipeline.last is not None
    listed = _SpyPipeline.last.listed
    assert [type(p) for p in listed] == [
        type(transport.input()),
        VADProcessor,
        RTVIProcessor,
        GroqSTTService,
        LLMUserAggregator,
        GroqLLMService,
        EdgeTTSService,
        type(transport.output()),
        LLMAssistantAggregator,
    ]
    llm = next(p for p in listed if isinstance(p, GroqLLMService))
    assert {"book_appointment", "available_slots"} <= set(llm._functions)  # type: ignore[attr-defined]


async def test_connect_queues_agent_info_then_greeting(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config()
    task, transport = bot.build_task(config, "test-key")
    seen = _spy_frames(task, monkeypatch)
    await _handler(transport, "on_client_connected")(transport, object())
    assert isinstance(seen[0], RTVIServerMessageFrame)
    info = seen[0].data["agent_info"]
    assert info["stt_model"] == config.stt_model
    assert info["llm_model"] == config.llm_model
    assert info["tts_voice"] == config.tts_voice
    assert isinstance(seen[1], LLMRunFrame)


async def test_disconnect_interrupts_but_keeps_the_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ending the pipeline on disconnect closed the server for a moment: a caller that
    # connected then was accepted and cut off, or refused (finding 3 of the M1 final
    # review). The pipeline stays up; a reply still in flight is cut off instead.
    task, transport = bot.build_task(load_config(), "test-key")
    seen = _spy_frames(task, monkeypatch)
    await _handler(transport, "on_client_disconnected")(transport, object())
    assert [type(f) for f in seen] == [InterruptionWorkerFrame]
    assert not any(isinstance(f, EndFrame) for f in seen)


class _SpyWorker(PipelineWorker):
    kwargs: dict[str, Any] = {}

    def __init__(self, pipeline: Any, **kwargs: Any) -> None:
        super().__init__(pipeline, **kwargs)
        _SpyWorker.kwargs = kwargs


def test_pipeline_is_never_cancelled_for_being_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    # One pipeline serves every call, so an idle spell between calls must not end it.
    monkeypatch.setattr(bot, "PipelineWorker", _SpyWorker)
    bot.build_task(load_config(), "test-key")
    assert _SpyWorker.kwargs["idle_timeout_secs"] is None


async def test_connect_starts_each_call_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    # The pipeline outlives a call, so everything a call leaves behind is reset when
    # the next caller connects: conversation, bookings and both aggregators.
    monkeypatch.setattr(bot, "Pipeline", _SpyPipeline)
    task, transport = bot.build_task(load_config(), "test-key")
    assert _SpyPipeline.last is not None
    listed = _SpyPipeline.last.listed
    llm = next(p for p in listed if isinstance(p, GroqLLMService))
    user = next(p for p in listed if isinstance(p, LLMUserAggregator))
    assistant = next(p for p in listed if isinstance(p, LLMAssistantAggregator))
    context = user._context
    resets: list[str] = []
    for name, aggregator in (("user", user), ("assistant", assistant)):

        async def reset(name: str = name) -> None:
            resets.append(name)

        monkeypatch.setattr(aggregator, "reset", reset)
    seen = _spy_frames(task, monkeypatch)

    slot = {"doctor": "dr-rao", "date": "2026-11-20", "time": "10:30", "phone": "9845012345"}
    assert (await _call_tool(llm, "book_appointment", slot))["ok"] is True
    context.add_message({"role": "user", "content": "the previous caller"})
    await _handler(transport, "on_client_connected")(transport, object())

    assert context.messages == []
    args = {"doctor": "dr-rao", "date": "2026-11-20"}
    assert "10:30" in (await _call_tool(llm, "available_slots", args))["slots"]
    assert sorted(resets) == ["assistant", "user"]
    assert [type(f) for f in seen] == [RTVIServerMessageFrame, LLMRunFrame]


async def _call_tool(llm: GroqLLMService, name: str, arguments: dict[str, str]) -> Any:
    results: list[Any] = []

    async def result_callback(value: Any, *_args: Any, **_kwargs: Any) -> None:
        results.append(value)

    params = SimpleNamespace(
        function_name=name, arguments=arguments, result_callback=result_callback
    )
    await llm._functions[name].handler(params)  # type: ignore[attr-defined]
    return results[0]


def _build_llm_and_context(monkeypatch: pytest.MonkeyPatch) -> tuple[GroqLLMService, Any]:
    monkeypatch.setattr(bot, "Pipeline", _SpyPipeline)
    bot.build_task(load_config(), "test-key")
    assert _SpyPipeline.last is not None
    listed = _SpyPipeline.last.listed
    llm = next(p for p in listed if isinstance(p, GroqLLMService))
    user = next(p for p in listed if isinstance(p, LLMUserAggregator))
    return llm, user._context


async def test_each_build_has_independent_state(monkeypatch: pytest.MonkeyPatch) -> None:
    llm1, context1 = _build_llm_and_context(monkeypatch)
    llm2, context2 = _build_llm_and_context(monkeypatch)
    assert context1 is not context2
    booked = await _call_tool(
        llm1,
        "book_appointment",
        {"doctor": "dr-rao", "date": "2026-11-20", "time": "10:30", "phone": "9845012345"},
    )
    assert booked["ok"] is True
    args = {"doctor": "dr-rao", "date": "2026-11-20"}
    assert "10:30" not in (await _call_tool(llm1, "available_slots", args))["slots"]
    assert "10:30" in (await _call_tool(llm2, "available_slots", args))["slots"]


def test_metrics_enabled_so_the_report_shows_agent_ttfb() -> None:
    # EC-77: the report puts the agent's own TTFB beside end-to-end latency. Pipecat sends
    # TTFB in RTVI metrics only with enable_metrics; the first live run had none.
    task, _transport = bot.build_task(load_config(), "test-key")
    assert task.params.enable_metrics is True
