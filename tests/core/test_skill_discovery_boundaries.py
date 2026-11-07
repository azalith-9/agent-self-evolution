"""Select a skill by exact identity and numeric release ordering."""

from __future__ import annotations

from pathlib import Path

from evolution.core.skill_sources import ClaudeCodeSkillSource, HermesSkillSource, LocalDirSkillSource


def test_latest_plugin_version_uses_numeric_components(tmp_path: Path) -> None:
    for version in ("0.9.0", "0.10.0"):
        skill = tmp_path / "vendor" / "plugin" / version / "skills" / "demo" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(version)
    found = ClaudeCodeSkillSource(tmp_path).find_skill("demo")
    assert found is not None and found.read_text() == "0.10.0"


def test_frontmatter_name_must_match_exactly(tmp_path: Path) -> None:
    skill = tmp_path / "skills/other/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: data-pipelines\n---\nbody")
    assert HermesSkillSource(tmp_path).find_skill("data") is None


def test_undecodable_unrelated_skill_does_not_block_discovery(tmp_path: Path) -> None:
    for directory, body in (("a-binary", b"\xff\xfe"),
                            ("b-renamed", b"---\nname: wanted\n---\nbody")):
        skill = tmp_path / "skills" / directory / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_bytes(body)
    found = HermesSkillSource(tmp_path).find_skill("wanted")
    assert found is not None and found.parent.name == "b-renamed"


def test_flat_source_cannot_select_parent_skill(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside/SKILL.md"
    outside.parent.mkdir()
    outside.write_text("outside")
    assert LocalDirSkillSource(root).find_skill("../outside") is None


def test_plugin_release_precedes_prerelease_and_nonversion_labels(tmp_path: Path) -> None:
    for version in ("1.2.0-rc.10", "1.2.0-rc.2", "1.2.0", "snapshot"):
        skill = tmp_path / "vendor" / "plugin" / version / "skills" / "demo" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(version)
    found = ClaudeCodeSkillSource(tmp_path).find_skill("demo")
    assert found is not None and found.read_text() == "1.2.0"
