"""Legality re-export: policy consumers import the legality matrix from here."""

from revive.classify.taxonomy import LEGAL_MOVES, legal_moves  # noqa: F401

__all__ = ["LEGAL_MOVES", "legal_moves"]
