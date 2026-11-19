"""Deterministic seeds from sha256, never from hash() or the clock."""

import hashlib

import numpy as np


def call_seed(scenario_id: str, preset: str) -> int:
    """63-bit seed for one scenario under one preset."""
    digest = hashlib.sha256(f"{scenario_id}\x00{preset}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def part_rng(call_seed: int, part: str) -> np.random.Generator:
    """Independent generator for one part of a call ("noise", "bed", "turn-<i>")."""
    digest = hashlib.sha256(f"{call_seed}:{part}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))
