import asyncio

import pytest
import yaml

from skeel.gh import InstalledSkill, update_steps
from skeel.io import ProcessResult
from skeel.manifest import Manifest, SkillSpec, SourceSpec
from skeel.targets import SkillTarget


@pytest.fixture
def setup(tmp_path):
    source = SourceSpec(
        source="local",
        skills=(
            SkillSpec(spec="alpha", name="alpha"),
            SkillSpec(spec="beta", name="beta", frontmatter={"description": "Managed"}),
        ),
        install=(("prepare", "argument with spaces"), ("generate",)),
    )
    target = SkillTarget(directory=tmp_path / "skills", scope="user", agent="universal")
    installed = []
    for spec in source.skills:
        path = target.directory / spec.name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(f"---\nname: {spec.name}\n---\n# Original\n")
        installed.append(InstalledSkill(name=spec.name, path=path))
    manifest = Manifest(path=tmp_path / "skills.yaml", sources=(source,))
    return source, target, installed, manifest


def test_custom_update_runs_once_per_source_in_order_with_environment(setup, monkeypatch):
    source, target, installed, manifest = setup
    calls = []

    async def run(self, command, *, capture_output, env):
        calls.append(command)
        assert capture_output
        assert env == {
            "SKEEL_AGENT": "universal",
            "SKEEL_SCOPE": "user",
            "SKEEL_SKILLS_DIR": str(target.directory),
            "SKEEL_MANIFEST": str(manifest.path),
        }
        return ProcessResult(command=command, returncode=0)

    monkeypatch.setattr("skeel.gh.ProcessRunner.run", run)
    steps = update_steps(installed, target, manifest=manifest)
    assert len(steps) == 1
    step = steps[0]
    assert step.label == "local@*"
    assert step.command == ["sh", "-c", "prepare 'argument with spaces' && generate"]
    assert step.executor is not None
    assert step.outcome is not None
    result = asyncio.run(step.executor())
    assert result.returncode == 0
    assert calls == [list(command) for command in source.install]
    assert step.outcome(result).status == "updated"
    frontmatter = (target.directory / "beta/SKILL.md").read_text().split("---")[1]
    assert yaml.safe_load(frontmatter)["description"] == "Managed"


@pytest.mark.parametrize("filename", ["SKILL.md", "scripts/helper.py"])
def test_custom_update_compares_content_not_timestamps(setup, monkeypatch, filename):
    _, target, installed, manifest = setup

    async def run(self, command, **kwargs):
        return ProcessResult(command=command, returncode=0)

    monkeypatch.setattr("skeel.gh.ProcessRunner.run", run)
    # Apply the frontmatter override first, so the next update is unchanged.
    initial = update_steps(installed, target, manifest=manifest)[0]
    asyncio.run(initial.executor())
    step = update_steps(installed, target, manifest=manifest)[0]
    result = asyncio.run(step.executor())
    assert step.outcome(result).status == "current"
    (target.directory / "alpha/SKILL.md").touch()
    assert step.outcome(result).status == "current"
    path = target.directory / "alpha" / filename
    path.parent.mkdir(exist_ok=True)
    path.write_text("Changed content")
    assert step.outcome(result).status == "updated"


def test_custom_update_stops_on_failure_and_preserves_output(setup, monkeypatch):
    _, target, installed, manifest = setup
    calls = []

    async def run(self, command, **kwargs):
        calls.append(command)
        return ProcessResult(command=command, returncode=7, stdout="partial", stderr="failed")

    monkeypatch.setattr("skeel.gh.ProcessRunner.run", run)
    step = update_steps(installed, target, manifest=manifest)[0]
    result = asyncio.run(step.executor())
    assert calls == [["prepare", "argument with spaces"]]
    assert result.returncode == 7
    assert result.stdout == "partial"
    assert result.stderr == "failed"
    assert "description" not in (target.directory / "beta/SKILL.md").read_text()


def test_custom_update_verifies_declared_outputs(setup, monkeypatch):
    _, target, installed, manifest = setup

    async def run(self, command, **kwargs):
        if command == ["generate"]:
            (target.directory / "beta/SKILL.md").unlink()
        return ProcessResult(command=command, returncode=0)

    monkeypatch.setattr("skeel.gh.ProcessRunner.run", run)
    step = update_steps(installed, target, manifest=manifest)[0]
    result = asyncio.run(step.executor())
    assert result.returncode == 1
    assert "did not produce skill(s) beta" in result.stderr


def test_custom_update_does_not_install_an_absent_source(setup):
    _, target, _, manifest = setup
    assert update_steps([], target, manifest=manifest) == []
