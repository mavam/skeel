Skeel now manages skills for individual agents, with dedicated targets, discovery-aware paths, and portable custom installers. It also makes reconciliation safe by preserving undeclared skills by default while providing explicit pruning and execution-time deletion safeguards.

## 💥 Breaking changes

### Safe reconciliation with opt-in pruning

`skeel apply` now preserves installed skills that the manifest does not declare. Pass `--prune` to restore the previous behavior of removing undeclared extras; `apply --dry-run --prune` previews the removals first.

`skeel remove <skill> --apply` now deletes exactly the deselected skill instead of pruning every undeclared skill in the target, so hand-authored and built-in agent skills survive a targeted removal. Whole-source removal matches both source provenance and every declared skill name. Custom installers must declare their produced skills before an applied whole-source removal, so Skeel never guesses which metadata-less directories they own. `--prune` is rejected with selective apply or `--reinstall` instead of being silently ignored.

Deletion also gained execution-time safety guards: skeel verifies that the planned target and skill directories have not been replaced, refuses symlinked skills, paths outside the resolved target, the target root itself, and directories without a regular `SKILL.md`. Symlinked target directories pin their resolved destination instead of aborting the entire apply. The same guards protect always-on pruning of skills removed upstream from pinned install-all sources during `update`.

*By @mavam in #21.*

## 🚀 Features

### Agent-specific skill targets

Skeel can now manage skill directories for specific agents. Pass `--agent` with any command to target an agent's own skill directory, or `--dir` for an explicit directory:

```sh
skeel --agent codex apply
skeel --agent pi -g list
skeel --dir ./custom/skills diff
```

The new `skeel agents` command lists all supported agents with their project and user skill directories, mirroring the GitHub CLI host registry. For a non-universal agent, project scope anchors at the enclosing git repository root so skills land where the agent discovers them. The `universal` target retains current-directory anchoring and project-over-user shadowing. Agent-specific targets reconcile project and user scope independently: when the same skill appears in both, skeel warns and lets the agent decide runtime precedence instead of skipping a copy. `skeel agents --json` reports absolute user paths. Claude Code's user directory reflects `CLAUDE_CONFIG_DIR`, expanding `~` and anchoring relative values at the home directory.

JSON output from `list` and `diff` now includes the target `agent` and `directory`, and both commands report `"scope": "custom"` for `--dir` targets.

Custom `install:` commands receive `SKEEL_AGENT`, `SKEEL_SCOPE`, `SKEEL_SKILLS_DIR`, and `SKEEL_MANIFEST` in their environment. `SKEEL_AGENT` is `universal` by default, the selected agent ID for `--agent`, and empty for `--dir`. Skeel verifies that declared skills appear in `SKEEL_SKILLS_DIR` after the installer runs and fails the step otherwise, so custom installers stay portable across agents.

*By @mavam in #21.*
