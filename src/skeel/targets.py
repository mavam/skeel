"""Skill installation targets and the agent host registry.

Skeel resolves agent names to canonical skill directories and keeps every
GitHub CLI invocation on ``--dir``. The registry mirrors the GitHub CLI host
registry (``internal/skills/registry/registry.go``) as of gh 2.97.0.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Scope = Literal["project", "user", "custom"]
TargetKind = Literal["universal", "agent", "custom"]

UNIVERSAL_SKILLS_DIR = ".agents/skills"
CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"


@dataclass(frozen=True)
class SkillTarget:
    """A canonical skill installation directory.

    The directory identifies the target; the agent name is display metadata
    and custom-installer environment only.
    """

    directory: Path
    scope: Scope = "custom"
    agent: str | None = None
    kind: TargetKind = "custom"

    @property
    def universal(self) -> bool:
        return self.kind == "universal"


@dataclass(frozen=True)
class AgentHost:
    id: str
    name: str
    project_dir: str
    user_dir: str


# Mirrors the gh CLI host registry ordering: popular agents first, then
# alphabetical by ID.
AGENT_HOSTS: tuple[AgentHost, ...] = (
    AgentHost("github-copilot", "GitHub Copilot", UNIVERSAL_SKILLS_DIR, ".copilot/skills"),
    AgentHost("claude-code", "Claude Code", ".claude/skills", ".claude/skills"),
    AgentHost("cursor", "Cursor", UNIVERSAL_SKILLS_DIR, ".cursor/skills"),
    AgentHost("codex", "Codex", UNIVERSAL_SKILLS_DIR, ".codex/skills"),
    AgentHost("gemini-cli", "Gemini CLI", UNIVERSAL_SKILLS_DIR, ".gemini/skills"),
    AgentHost("antigravity", "Antigravity", UNIVERSAL_SKILLS_DIR, ".gemini/antigravity/skills"),
    AgentHost(
        "antigravity-cli",
        "Antigravity CLI",
        UNIVERSAL_SKILLS_DIR,
        ".gemini/antigravity-cli/skills",
    ),
    AgentHost("antigravity2.0", "Antigravity 2.0", UNIVERSAL_SKILLS_DIR, ".gemini/config/skills"),
    AgentHost("adal", "AdaL", ".adal/skills", ".adal/skills"),
    AgentHost("amp", "Amp", UNIVERSAL_SKILLS_DIR, ".config/agents/skills"),
    AgentHost("augment", "Augment", ".augment/skills", ".augment/skills"),
    AgentHost("bob", "IBM Bob", ".bob/skills", ".bob/skills"),
    AgentHost("cline", "Cline", UNIVERSAL_SKILLS_DIR, ".agents/skills"),
    AgentHost("codebuddy", "CodeBuddy", ".codebuddy/skills", ".codebuddy/skills"),
    AgentHost("command-code", "Command Code", ".commandcode/skills", ".commandcode/skills"),
    AgentHost("continue", "Continue", ".continue/skills", ".continue/skills"),
    AgentHost("cortex", "Cortex Code", ".cortex/skills", ".snowflake/cortex/skills"),
    AgentHost("crush", "Crush", ".crush/skills", ".config/crush/skills"),
    AgentHost("deepagents", "Deep Agents", UNIVERSAL_SKILLS_DIR, ".deepagents/agent/skills"),
    AgentHost("devin", "Devin", ".devin/skills", ".devin/skills"),
    AgentHost("droid", "Droid", ".factory/skills", ".factory/skills"),
    AgentHost("firebender", "Firebender", UNIVERSAL_SKILLS_DIR, ".firebender/skills"),
    AgentHost("goose", "Goose", ".goose/skills", ".config/goose/skills"),
    AgentHost("grok", "Grok", ".grok/skills", ".grok/skills"),
    AgentHost("iflow-cli", "iFlow CLI", ".iflow/skills", ".iflow/skills"),
    AgentHost("junie", "Junie", ".junie/skills", ".junie/skills"),
    AgentHost("kilo", "Kilo Code", ".kilocode/skills", ".kilocode/skills"),
    AgentHost("kimi-cli", "Kimi Code CLI", UNIVERSAL_SKILLS_DIR, ".config/agents/skills"),
    AgentHost("kiro-cli", "Kiro CLI", ".kiro/skills", ".kiro/skills"),
    AgentHost("kode", "Kode", ".kode/skills", ".kode/skills"),
    AgentHost("mcpjam", "MCPJam", ".mcpjam/skills", ".mcpjam/skills"),
    AgentHost("mistral-vibe", "Mistral Vibe", ".vibe/skills", ".vibe/skills"),
    AgentHost("mux", "Mux", ".mux/skills", ".mux/skills"),
    AgentHost("neovate", "Neovate", ".neovate/skills", ".neovate/skills"),
    AgentHost("openclaw", "OpenClaw", "skills", ".openclaw/skills"),
    AgentHost("opencode", "OpenCode", UNIVERSAL_SKILLS_DIR, ".config/opencode/skills"),
    AgentHost("openhands", "OpenHands", ".openhands/skills", ".openhands/skills"),
    AgentHost("pi", "Pi", ".pi/skills", ".pi/agent/skills"),
    AgentHost("pochi", "Pochi", ".pochi/skills", ".pochi/skills"),
    AgentHost("qoder", "Qoder", ".qoder/skills", ".qoder/skills"),
    AgentHost("qwen-code", "Qwen Code", ".qwen/skills", ".qwen/skills"),
    AgentHost("replit", "Replit", UNIVERSAL_SKILLS_DIR, ".config/agents/skills"),
    AgentHost("roo", "Roo Code", ".roo/skills", ".roo/skills"),
    AgentHost("trae", "Trae", ".trae/skills", ".trae/skills"),
    AgentHost("trae-cn", "Trae CN", ".trae/skills", ".trae-cn/skills"),
    AgentHost("universal", "Universal", UNIVERSAL_SKILLS_DIR, UNIVERSAL_SKILLS_DIR),
    AgentHost("warp", "Warp", UNIVERSAL_SKILLS_DIR, ".agents/skills"),
    AgentHost("zencoder", "Zencoder", ".zencoder/skills", ".zencoder/skills"),
)

_HOSTS_BY_ID = {host.id: host for host in AGENT_HOSTS}


def find_agent(name: str) -> AgentHost:
    host = _HOSTS_BY_ID.get(name)
    if host is None:
        raise ValueError(
            f'unknown agent "{name}"; run `skeel agents` to list supported agents, '
            "or use --dir for a custom skills directory"
        )
    return host


def git_root(start: Path) -> Path | None:
    """Return the enclosing git repository root, or None outside a repo."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def project_base(cwd: Path, *, agent: str | None) -> Path:
    """Anchor for project-scope paths.

    Named agents anchor at the git repository root so skills land where the
    agent discovers them, falling back to the working directory outside a
    repository. The universal target keeps its historical cwd anchoring.
    """
    if agent in (None, "universal"):
        return cwd
    return git_root(cwd) or cwd


def agent_user_directory_override(host: AgentHost, home: Path) -> Path | None:
    if host.id != "claude-code" or not (config_dir := os.environ.get(CLAUDE_CONFIG_DIR_ENV)):
        return None
    if config_dir == "~":
        path = home
    elif config_dir.startswith("~/"):
        path = home / config_dir[2:]
    else:
        path = Path(config_dir).expanduser()
        if not path.is_absolute():
            path = home / path
    return path / "skills"


def agent_user_directory(host: AgentHost, home: Path) -> Path:
    return agent_user_directory_override(host, home) or home / host.user_dir


def resolve_target(
    *,
    scope: Scope,
    agent: str | None = None,
    directory: str | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
) -> SkillTarget:
    """Resolve an installation target from CLI selectors."""
    if directory is not None:
        return SkillTarget(directory=Path(directory).expanduser(), scope="custom", kind="custom")

    cwd = cwd or Path.cwd()
    home = home or Path.home()
    host = find_agent(agent or "universal")
    if host.id == "universal":
        base = home if scope == "user" else cwd
        return SkillTarget(
            directory=base / UNIVERSAL_SKILLS_DIR,
            scope=scope,
            agent=host.id,
            kind="universal",
        )
    if scope == "user":
        return SkillTarget(
            directory=agent_user_directory(host, home),
            scope="user",
            agent=host.id,
            kind="agent",
        )
    base = project_base(cwd, agent=host.id)
    return SkillTarget(
        directory=base / host.project_dir,
        scope="project",
        agent=host.id,
        kind="agent",
    )
