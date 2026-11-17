import pytest

from agents.clinic_agent.config import AgentConfig, load_config, verify_models


def test_config_loads() -> None:
    config = load_config()
    assert config.stt_model == "whisper-large-v3-turbo"
    assert config.stt_language == "hi"
    assert config.sample_rate == 16000


def test_verify_models_missing() -> None:
    config = load_config()
    with pytest.raises(RuntimeError, match=r"openai/gpt-oss-20b"):
        verify_models({"whisper-large-v3-turbo"}, config)


def test_verify_models_ok() -> None:
    config = load_config()
    verify_models({config.stt_model, config.llm_model}, config)


def test_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError):
        AgentConfig.model_validate({"surprise": 1})
