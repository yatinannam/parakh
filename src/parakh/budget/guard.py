"""Refuse to send real data to remote APIs; only synthetic data may leave the machine."""


class RealDataRefused(RuntimeError):
    """Raised when a remote call would carry real (non-synthetic) data."""


def remote_call(provider: str, *, real: bool) -> None:
    """Gate a call to a remote provider. Raises if the payload is real data."""
    if real:
        raise RealDataRefused(
            f"Refusing to send real data to {provider}: free tiers may train on it. "
            "Use synthetic data only."
        )
