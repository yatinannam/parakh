import numpy as np
import pytest

from parakh.degrade.loss import apply_loss, loss_mask


@pytest.mark.parametrize(("rate", "burst"), [(0.03, None), (0.05, 3.0)])
def test_loss_rate_within_one_percent(rate: float, burst: float | None) -> None:
    mask = loss_mask(100_000, rate, burst, np.random.default_rng(1))
    assert float(mask.mean()) == pytest.approx(rate, abs=0.01)


def test_mean_burst_length() -> None:
    mask = loss_mask(100_000, 0.05, 3.0, np.random.default_rng(2))
    padded = np.concatenate([[False], mask, [False]]).astype(int)
    edges = np.diff(padded)
    runs = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
    assert float(runs.mean()) == pytest.approx(3.0, abs=0.3)


def test_conceal_zero_and_repeat() -> None:
    x = np.arange(1, 41, dtype=np.float64)
    mask = np.array([False, True, True, False])
    zero = apply_loss(x, 10, mask, "zero")
    assert np.all(zero[10:30] == 0)
    assert np.array_equal(zero[:10], x[:10])
    assert np.array_equal(zero[30:], x[30:])
    rep = apply_loss(x, 10, mask, "repeat")
    assert np.array_equal(rep[10:20], x[:10])
    assert np.array_equal(rep[20:30], x[:10])
    first = apply_loss(x, 10, np.array([True, False, False, False]), "repeat")
    assert np.all(first[:10] == 0)


def test_apply_loss_partial_last_frame() -> None:
    x = np.ones(25)
    out = apply_loss(x, 10, np.array([False, False, True]), "zero")
    assert np.all(out[20:] == 0) and len(out) == 25
    out = apply_loss(x * np.arange(25), 10, np.array([False, False, True]), "repeat")
    assert np.array_equal(out[20:], np.arange(10, 15))
