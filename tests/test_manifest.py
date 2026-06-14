from pathlib import Path

import pytest

from skeel.manifest import infer_skill_name, load_manifest, manifest_path


def write_manifest(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "skills.yaml"
    path.write_text(content.strip())
    return path


@pytest.mark.parametrize(
    ("spec", "name"),
    [
        ("mavam", "mavam"),
        ("skills/foo/SKILL.md", "foo"),
        ("packages/agent-skills/code-review", "code-review"),
    ],
)
def test_infer_skill_name(spec: str, name: str) -> None:
    assert infer_skill_name(spec) == name


def test_wildcard_is_rejected() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        infer_skill_name("*")


def test_default_manifest_path() -> None:
    assert manifest_path() == Path("~/.agents/skills.yaml").expanduser()


def test_load_manifest_sources(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  - tenzir/skills@tenzir-docs
  - mavam/quarto-brief
  - github: openclaw/gogcli
    skills:
      - gog
  - github: mattpocock/skills
    pin: v1
    skills:
      - caveman
      - grill-me
""".strip(),
    )

    manifest = load_manifest(path)

    assert manifest.path == path
    assert manifest.desired_skill_names == {"tenzir-docs", "gog", "caveman", "grill-me"}
    assert manifest.has_dynamic_sources is True

    shorthand, dynamic, explicit, pinned = manifest.sources
    assert (shorthand.source, shorthand.skills[0].name, shorthand.install_all) == (
        "tenzir/skills",
        "tenzir-docs",
        False,
    )
    assert (dynamic.source, dynamic.skills, dynamic.install_all) == (
        "mavam/quarto-brief",
        (),
        True,
    )
    assert explicit.source == "openclaw/gogcli"
    assert explicit.skills[0].name == "gog"
    assert [skill.pin for skill in pinned.skills] == ["v1", "v1"]


def test_source_shorthand_rejects_pins(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  - tenzir/skills@tenzir-docs@v1
""".strip(),
    )

    with pytest.raises(ValueError, match="mapping form for pins"):
        load_manifest(path)


def test_manual_install_source_tracks_desired_skills(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  - skills:
      - clacks
      - name: clacks-claude
        path: clacks
    install:
      - uvx --from slack-clacks clacks skill --mode universal
      - [uvx, --from, slack-clacks, clacks, skill, --mode, claude]
""".strip(),
    )

    manifest = load_manifest(path)

    assert manifest.desired_skill_names == {"clacks", "clacks-claude"}
    assert manifest.sources[0].source is None
    assert manifest.sources[0].install == (
        ("uvx", "--from", "slack-clacks", "clacks", "skill", "--mode", "universal"),
        ("uvx", "--from", "slack-clacks", "clacks", "skill", "--mode", "claude"),
    )


def test_source_without_skills_installs_all(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  - github: mavam/quarto-brief
""".strip(),
    )

    manifest = load_manifest(path)

    assert manifest.sources[0].source == "mavam/quarto-brief"
    assert manifest.sources[0].skills == ()
    assert manifest.sources[0].install_all is True


def test_source_and_github_conflict_is_rejected(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  - source: owner/one
    github: owner/two
    skills:
      - skill
""".strip(),
    )

    with pytest.raises(ValueError, match="cannot define both"):
        load_manifest(path)


def test_manual_install_source_requires_skills(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources:
  - install:
      - uvx --from slack-clacks clacks skill --mode universal
""".strip(),
    )

    with pytest.raises(ValueError, match="has no skills"):
        load_manifest(path)


def test_manifest_requires_sources(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        """
sources: []
""".strip(),
    )

    with pytest.raises(ValueError, match="at least one source"):
        load_manifest(path)
