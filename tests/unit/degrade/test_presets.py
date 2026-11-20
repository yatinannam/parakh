from importlib.resources import files

import pytest

from parakh.degrade.presets import (
    PRESET_ORDER,
    NoiseSpec,
    Preset,
    expand_presets,
    get_preset,
    load_presets,
    load_talkers,
)


def test_five_presets_in_order() -> None:
    assert PRESET_ORDER == ("clean", "phone", "phone_noisy", "phone_lossy", "bad_line")
    assert tuple(load_presets()) == PRESET_ORDER


def test_preset_values() -> None:
    p = load_presets()
    assert p["clean"] == Preset(name="clean")
    assert p["phone"] == Preset(name="phone", telephone=True)
    noisy = p["phone_noisy"]
    assert noisy.telephone and noisy.noise == NoiseSpec(kind="babble", snr_db=10.0)
    assert noisy.loss is None and noisy.clip_dbfs is None
    lossy = p["phone_lossy"]
    assert lossy.telephone and lossy.noise is None and lossy.clip_dbfs is None
    assert lossy.loss is not None
    assert (lossy.loss.rate, lossy.loss.mean_burst_frames) == (0.03, None)
    bad = p["bad_line"]
    assert bad.telephone and bad.noise == NoiseSpec(kind="pink", snr_db=5.0)
    assert bad.loss is not None
    assert (bad.loss.rate, bad.loss.mean_burst_frames, bad.loss.conceal) == (0.05, 3.0, "zero")
    assert bad.clip_dbfs == -10.0


def test_unknown_preset_lists_available() -> None:
    with pytest.raises(ValueError, match=r"unknown preset 'x'; available: clean, phone, "):
        get_preset("x")
    assert get_preset("phone").telephone


def test_six_talkers() -> None:
    talkers = load_talkers()
    assert [t.voice for t in talkers] == [
        "hi-IN-SwaraNeural",
        "hi-IN-MadhurNeural",
        "en-IN-NeerjaNeural",
        "en-IN-PrabhatNeural",
        "hi-IN-SwaraNeural",
        "hi-IN-MadhurNeural",
    ]
    assert [t.rate for t in talkers] == ["+0%"] * 4 + ["+10%"] * 2
    for t in talkers:
        assert 15 <= len(t.text.split()) <= 25
        assert t.text.isascii()


def test_presets_yaml_ships_in_wheel() -> None:
    # hatchling ships every file under src/parakh; this proves the loader's access path.
    assert files("parakh.degrade").joinpath("presets.yaml").is_file()


def test_expand_presets_all_dedupes_and_keeps_order():
    assert expand_presets(["all"]) == list(PRESET_ORDER)
    assert expand_presets(["phone", "clean", "phone"]) == ["phone", "clean"]
    assert expand_presets(["phone", "all"])[0] == "phone"
    assert len(expand_presets(["phone", "all"])) == len(PRESET_ORDER)


def test_expand_presets_unknown_raises():
    with pytest.raises(ValueError, match="unknown preset"):
        expand_presets(["clean", "telephone"])
