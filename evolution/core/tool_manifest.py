"""Structural tool metadata consumed by framework-independent dataset generation."""

from __future__ import annotations

from typing import Protocol, Sequence


class ToolDescription(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...


class ToolManifest(Protocol):
    @property
    def tools(self) -> Sequence[ToolDescription]: ...

    def confusable_neighbor_for(self, tool_name: str) -> str | None: ...


def normalize_tool_name(name: str) -> str:
    """Use the same spelling for tool lookup, collisions, and dataset filtering."""
    return name.lower().replace("-", "_")
