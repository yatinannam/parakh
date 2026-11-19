"""Telephone-line degradation: codec, band filters, noise and loss."""

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
from parakh.degrade.mulaw import mulaw_decode, mulaw_encode, mulaw_saturated

__all__ = [
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
