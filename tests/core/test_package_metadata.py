"""Minimal distributable-license and fork metadata verification."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_declared_mit_license_has_distributable_terms() -> None:
    license_text = (ROOT / "LICENSE").read_text()
    assert "Permission is hereby granted, free of charge" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text
    assert "MIT — © 2026 [azalith-9](https://github.com/azalith-9) / [jramos](https://github.com/jramos) / [Nous Research](https://github.com/NousResearch)" in (ROOT / "README.md").read_text()


def test_package_urls_identify_current_repository() -> None:
    text = (ROOT / "pyproject.toml").read_text()
    urls = text.split("[project.urls]\n", 1)[1].split("\n[", 1)[0]
    expected = '"https://github.com/azalith-9/agent-self-evolution"'
    assert f"Homepage = {expected}" in urls
    assert f"Repository = {expected}" in urls
