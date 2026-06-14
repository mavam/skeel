from pathlib import Path

import pytest

from skeel.manifest import infer_skill_name, load_manifest


def test_infer_skill_name_from_plain_name() -> None:
    assert infer_skill_name("mavam") == "mavam"


def test_infer_skill_name_from_skill_path() -> None:
    assert infer_skill_name("skills/foo/SKILL.md") == "foo"


def test_wildcard_is_rejected() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        infer_skill_name("*")


def test_load_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "skills.yaml"
    manifest_path.write_text(
        """
version: 1
shared_dir: ~/.agents/skills
agents:
  - universal
  - claude-code
sources:
  - source: mavam/skills
    private: true
    skills:
      - mavam
  - source: openclaw/gogcli
    allow-hidden-dirs: true
    skills:
      - gog
""".strip()
    )

    manifest = load_manifest(manifest_path)

    assert manifest.path == manifest_path
    assert manifest.agents == ("universal", "claude-code")
    assert manifest.desired_skill_names == {"mavam", "gog"}
    assert manifest.sources[1].allow_hidden_dirs is True
