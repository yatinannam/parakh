"""Telephone-line degradation: codec, band filters, noise and loss."""

from parakh.degrade.chain import FRAME_MS, Degraded, DegradeStats, degrade
from parakh.degrade.filters import (
    BAND_HZ,
    F64,
    PEAK_DBFS,
    TELEPHONE_RATE,
    band_limit,
    hard_clip,
    peak_normalise,
    resample_f,
    telephone,
    to_int16,
)
from parakh.degrade.loss import apply_loss, loss_mask
from parakh.degrade.mulaw import mulaw_decode, mulaw_encode, mulaw_saturated
from parakh.degrade.noise import (
    DegradeError,
    brown,
    measured_snr_db,
    noise_scale,
    noise_slice,
    pink,
    speech_active_rms,
    white,
)
from parakh.degrade.presets import (
    PRESET_ORDER,
    LossSpec,
    NoiseSpec,
    Preset,
    Talker,
    get_preset,
    load_presets,
    load_talkers,
)
from parakh.degrade.seeds import call_seed, part_rng

__all__ = [
    "FRAME_MS",
    "Degraded",
    "DegradeStats",
    "degrade",
    "apply_loss",
    "loss_mask",
    "DegradeError",
    "brown",
    "measured_snr_db",
    "noise_scale",
    "noise_slice",
    "pink",
    "speech_active_rms",
    "white",
    "PRESET_ORDER",
    "LossSpec",
    "NoiseSpec",
    "Preset",
    "Talker",
    "get_preset",
    "load_presets",
    "load_talkers",
    "call_seed",
    "part_rng",
    "BAND_HZ",
    "F64",
    "PEAK_DBFS",
    "TELEPHONE_RATE",
    "band_limit",
    "hard_clip",
    "mulaw_decode",
    "mulaw_encode",
    "mulaw_saturated",
    "peak_normalise",
    "resample_f",
    "telephone",
    "to_int16",
]
