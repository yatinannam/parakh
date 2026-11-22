"""Pipecat pipeline for the Parakh Clinic test agent."""

import importlib.metadata

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import InterruptionWorkerFrame, LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frameworks.rtvi import (
    RTVIObserver,
    RTVIProcessor,
    RTVIServerMessageFrame,
)
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transcriptions.language import Language
from pipecat.transports.websocket.server import (
    SingleClientWebsocketServerParams,
    SingleClientWebsocketServerTransport,
)

from agents.clinic_agent.config import AgentConfig
from agents.clinic_agent.prompt import system_prompt
from agents.clinic_agent.reset import ClinicSTT, ClinicVAD
from agents.clinic_agent.tools import BookingStore, tool_schemas
from agents.clinic_agent.tts_edge import EdgeTTSService
from parakh.tts.engine import EdgeTTSEngine

PIPECAT_VERSION = importlib.metadata.version("pipecat-ai")


def build_task(
    config: AgentConfig,
    groq_api_key: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> tuple[PipelineWorker, SingleClientWebsocketServerTransport]:
    rate = config.sample_rate
    transport = SingleClientWebsocketServerTransport(
        params=SingleClientWebsocketServerParams(
            serializer=ProtobufFrameSerializer(),
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=rate,
            audio_out_sample_rate=rate,
        ),
        host=host,
        port=port,
    )
    stt = ClinicSTT(
        api_key=groq_api_key,
        settings=ClinicSTT.Settings(model=config.stt_model, language=Language(config.stt_language)),
    )
    llm = GroqLLMService(
        api_key=groq_api_key,
        settings=GroqLLMService.Settings(
            model=config.llm_model, system_instruction=system_prompt(config)
        ),
    )
    store = BookingStore()

    async def book_appointment(params: FunctionCallParams) -> None:
        await params.result_callback(store.book_appointment(**params.arguments))

    async def available_slots(params: FunctionCallParams) -> None:
        slots = store.available_slots(**params.arguments)
        await params.result_callback({"slots": slots})

    llm.register_function("book_appointment", book_appointment)
    llm.register_function("available_slots", available_slots)

    tts = EdgeTTSService(engine=EdgeTTSEngine(), voice=config.tts_voice, sample_rate=rate)
    context = LLMContext(tools=tool_schemas())
    aggregators = LLMContextAggregatorPair(context)
    rtvi = RTVIProcessor()
    vad = ClinicVAD(vad_analyzer=SileroVADAnalyzer())

    pipeline = Pipeline(
        [
            transport.input(),
            vad,
            rtvi,
            stt,
            aggregators.user(),
            llm,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )
    task = PipelineWorker(
        pipeline,
        # Metrics on: RTVI metrics then carry STT, LLM and TTS TTFB for the report (EC-77).
        # Usage metrics add the LLM token counts (EC-84).
        params=PipelineParams(
            audio_in_sample_rate=rate,
            audio_out_sample_rate=rate,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[RTVIObserver(rtvi)],
        # One pipeline serves every call; an idle spell between calls must not end it.
        idle_timeout_secs=None,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport, _client) -> None:
        # The pipeline outlives each call, so start this one from an empty
        # conversation and booking store. The system prompt lives in the LLM settings.
        vad.reset_call()
        stt.reset_call()
        context.set_messages([])
        store.reset()
        await aggregators.user().reset()
        await aggregators.assistant().reset()
        info = {
            "agent_info": {
                "stt_model": config.stt_model,
                "llm_model": config.llm_model,
                "tts_voice": config.tts_voice,
                "pipecat": PIPECAT_VERSION,
            }
        }
        await task.queue_frames([RTVIServerMessageFrame(data=info), LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _client) -> None:
        # Keep the pipeline and its server up, so the next caller is accepted at once;
        # ending it here closed the server for a moment, and a caller who connected
        # then was cut off or refused. Cut off any reply still in flight instead, so
        # none of it reaches the next caller. Speech state goes too: a segment open at
        # hang-up must not surface in the next call.
        vad.reset_call()
        stt.reset_call()
        await task.queue_frame(InterruptionWorkerFrame())

    return task, transport
