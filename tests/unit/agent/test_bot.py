import pytest

from agents.clinic_agent.config import load_config


# Pipecat's websocket transport uses a deprecated websockets API, and PipelineTask is deprecated
# in 1.16 in favour of PipelineWorker. The brief fixes PipelineTask, so both are ignored here.
@pytest.mark.filterwarnings("ignore:websockets.*deprecated:DeprecationWarning")
@pytest.mark.filterwarnings("ignore:`PipelineTask` is deprecated:DeprecationWarning")
def test_build_task_offline() -> None:
    from agents.clinic_agent.bot import build_task

    task, transport = build_task(load_config(), "test-key")
    assert task is not None
    assert transport is not None
