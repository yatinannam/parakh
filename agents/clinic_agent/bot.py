"""Pipecat pipeline for the Parakh Clinic test agent."""

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame, LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frameworks.rtvi import (
    RTVIObserver,
    RTVIProcessor,
    RTVIServerMessageFrame,
)
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.groq.stt import GroqSTTService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transcriptions.language import Language
from pipecat.transports.websocket.server import (
    SingleClientWebsocketServerParams,
    SingleClientWebsocketServerTransport,
)

from agents.clinic_agent.config import AgentConfig
from agents.clinic_agent.prompt import system_prompt
from agents.clinic_agent.tools import BookingStore, tool_schemas
from agents.clinic_agent.tts_edge import EdgeTTSService
from parakh.tts.engine import EdgeTTSEngine

PIPECAT_VERSION = "1.16.0"


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
    stt = GroqSTTService(
        api_key=groq_api_key,
        settings=GroqSTTService.Settings(
            model=config.stt_model, language=Language(config.stt_language)
        ),
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

    pipeline = Pipeline(
        [
            transport.input(),
            VADProcessor(vad_analyzer=SileroVADAnalyzer()),
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
        params=PipelineParams(audio_in_sample_rate=rate, audio_out_sample_rate=rate),
        observers=[RTVIObserver(rtvi)],
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport, _client) -> None:
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
        # One call per task: end it so the next caller gets fresh state from a new task.
        await task.queue_frame(EndFrame())

    return task, transport
