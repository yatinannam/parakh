import pytest

from parakh.budget.guard import RealDataRefused, remote_call


def test_remote_call_refuses_real() -> None:
    with pytest.raises(RealDataRefused):
        remote_call("edge-tts", real=True)
    assert remote_call("edge-tts", real=False) is None
