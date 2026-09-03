"""Observability sidecars (currently: optional Phoenix integration).

This package is intentionally a *graceful no-op* when no sidecar is
installed. The 289+ existing tests run keyless (no Phoenix), exercising
the no-op path. The :func:`is_available` function is the single
contract: True if the sidecar is installed, False otherwise.

See :mod:`cadence.observability.phoenix` for the Phoenix integration and
the test suite for the no-op behavior.
"""

from __future__ import annotations

from cadence.observability.phoenix import (
    instrument,
    is_available,
    recent_traces,
)

__all__ = ["instrument", "is_available", "recent_traces"]
