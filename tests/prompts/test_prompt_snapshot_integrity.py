"""The offsets and bytes in a prompt splice must come from one read snapshot."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from evolution.prompts.hermes_prompt_source import HermesPromptSource


def test_prompt_splice_never_mixes_two_file_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "agent/prompt_builder.py"
    path.parent.mkdir()
    first = b"GUIDANCE = 'old'\nOTHER = 'keep'\n"
    second = b"GUIDANCE = 'much-longer-value'\nOTHER = 'changed-by-peer'\n"
    path.write_bytes(first)
    source = HermesPromptSource(tmp_path)
    read_text, read_bytes = Path.read_text, Path.read_bytes
    reads = []

    def bytes_snapshot(self: Path, *args: object, **kwargs: object) -> bytes:
        if self == path:
            reads.append("bytes")
            return first if len(reads) == 1 else second
        return read_bytes(self, *args, **kwargs)

    def text_snapshot(self: Path, *args: object, **kwargs: object) -> str:
        if self == path:
            reads.append("text")
            return first.decode() if len(reads) == 1 else second.decode()
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", bytes_snapshot)
    monkeypatch.setattr(Path, "read_text", text_snapshot)
    source.write("GUIDANCE", "new")
    actual = read_bytes(path)
    values = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(actual).body}
    assert values == {"GUIDANCE": "new", "OTHER": "keep"}
    assert len(reads) == 1
