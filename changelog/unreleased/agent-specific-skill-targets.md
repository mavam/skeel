---
title: Agent-specific skill targets
type: feature
authors:
  - mavam
prs:
  - 21
created: 2026-08-12T05:40:43.561556Z
---

Skeel can now manage skill directories for specific agents. Pass `--agent`
with any command to target an agent's own skill directory, or `--dir` for an
explicit directory:

```sh
skeel --agent codex apply
skeel --agent pi -g list
skeel --dir ./custom/skills diff
```

The new `skeel agents` command lists all supported agents with their project
and user skill directories, mirroring the GitHub CLI host registry. For a
non-universal agent, project scope anchors at the enclosing git repository root
so skills land where the agent discovers them. The `universal` target retains
current-directory anchoring and project-over-user shadowing. Agent-specific
targets reconcile project and user scope independently: when the same skill
appears in both, skeel warns and lets the agent decide runtime precedence
instead of skipping a copy. `skeel agents --json` reports absolute user
paths. Claude Code's user directory reflects `CLAUDE_CONFIG_DIR`, expanding
`~` and anchoring relative values at the home directory.

JSON output from `list` and `diff` now includes the target `agent` and
`directory`, and both commands report `"scope": "custom"` for `--dir` targets.

Custom `install:` commands receive `SKEEL_AGENT`, `SKEEL_SCOPE`,
`SKEEL_SKILLS_DIR`, and `SKEEL_MANIFEST` in their environment. `SKEEL_AGENT`
is `universal` by default, the selected agent ID for `--agent`, and empty for
`--dir`. Skeel verifies
that declared skills appear in `SKEEL_SKILLS_DIR` after the installer runs
and fails the step otherwise, so custom installers stay portable across
agents.
