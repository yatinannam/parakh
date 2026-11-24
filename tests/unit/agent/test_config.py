import pytest

from agents.clinic_agent.config import AgentConfig, load_config, verify_models


def test_config_loads() -> None:
    config = load_config()
    assert config.stt_model == "whisper-large-v3-turbo"
    assert config.stt_language == "hi"
    assert config.sample_rate == 16000


def test_tts_voice_speaks_devanagari() -> None:
    # The LLM often answers a Devanagari transcript in Devanagari. en-IN-NeerjaNeural
    # returns no audio for Devanagari text (edge-tts NoAudioReceived), which left the
    # agent silent and the call ended in turn_timeout; hi-IN-SwaraNeural speaks
    # Devanagari, English and Roman Hinglish.
    assert load_config().tts_voice == "hi-IN-SwaraNeural"


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


def test_profiles_fill_language_and_voice() -> None:
    expected = {
        "hi": ("hi", "hi-IN-SwaraNeural"),
        "kn": ("kn", "kn-IN-SapnaNeural"),
        "ta": ("ta", "ta-IN-PallaviNeural"),
    }
    for key, (language, voice) in expected.items():
        config = load_config(profile=key)
        assert config.profile == key
        assert (config.stt_language, config.tts_voice) == (language, voice)
    assert load_config().profile == "hi"


def test_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match=r"hi, kn, ta"):
        load_config(profile="xx")
