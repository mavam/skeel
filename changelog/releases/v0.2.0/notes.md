This release makes skeel manage skill manifests as editable desired state with JSON output for automation. It also improves reconciliation, updates, and pinned GitHub reinstalls so managed skills stay accurate and fast to refresh.

## 🚀 Features

### Custom skill installers in manifests

Manifest sources can now define custom install commands for skills that are not installed through `gh skill`:

```yaml
sources:
  slack-clacks/clacks:
    skills:
      - clacks
    install:
      - uvx --from slack-clacks clacks skill --mode universal --force
```

When `install` is present, skeel treats those commands as the complete install command set for the source. This keeps non-GitHub skill installers in the same desired-state manifest as regular `gh skill` sources.

*By @mavam.*

### Desired-state editing and JSON output

The CLI can now inspect and edit desired state directly.

```sh
skeel list
skeel add tenzir/skills tenzir-docs@main
skeel remove tenzir/skills tenzir-docs
skeel add mavam/quarto-brief --apply
```

`skeel list` shows each manifest skill and whether it is installed. `skeel add` upserts a source or skill into the manifest, and `skeel remove` removes a skill or the whole source. Passing `--apply` to either editing command reconciles installed skills immediately after saving the manifest.

Use `--json` with `list`, `diff`, `apply`, `add`, `remove`, and `update` to get one machine-readable JSON object on stdout for scripts and automation.

*By @mavam.*

## 🔧 Changes

### Keyed manifests and scope-based targets

The manifest format now uses source names as YAML keys and chooses install targets from CLI scope instead of manifest fields.

Before:

```yaml
shared_dir: ~/.agents/skills
agents:
  - claude-code
sources:
  - source: tenzir/skills
    skills:
      - tenzir-docs
```

After:

```yaml
sources:
  tenzir/skills:
    - tenzir-docs
  mavam/quarto-brief:
```

A list selects specific skills, an empty value installs all skills from that source, and a nested mapping is used for options such as `pin` and `install`. The previous list-of-source-objects shape and manifest-level target options such as `shared_dir`, `agents`, and `allow_hidden_dirs` are no longer supported.

Scope now determines both the implicit manifest path and the managed skill directory: project scope uses `.agents/skills.yaml` and `.agents/skills` in the current working directory, while user scope uses `~/.agents/skills.yaml` and `~/.agents/skills`.

*By @mavam.*

### Per-skill update results

`skeel update` now checks installed manifest skills one at a time and reports the outcome for each skill.

```sh
skeel update
skeel update --dry-run
```

The human output marks updated skills with `✔`, skills that were already current with `•`, and installed skills that were left unchanged with `◦`. When GitHub provenance is available, update output also shows version changes such as `main@oldsha → main@newsha`.

*By @mavam.*

### Reconciled apply workflow

`skeel apply` now reconciles installed skills with the manifest instead of only installing missing entries.

```sh
skeel apply
skeel apply --dry-run
skeel apply --reinstall
skeel apply --reinstall tenzir/skills
skeel apply tenzir/skills tenzir-docs
```

By default, apply installs missing manifest skills and removes extra skills from the managed directory. Targeted apply limits reconciliation to one source or skill, and `--reinstall` reruns installers without first computing drift.

Dry-run flags now work before or after mutating subcommands, so both `skeel --dry-run apply` and `skeel apply --dry-run` preview commands without changing files. Human output uses concise clypi status lines and spinners while commands run.

*By @mavam.*

## 🐞 Bug fixes

### Fast pinned GitHub skill reinstalls

Reinstalling pinned GitHub skill sources is now fast enough for large skill repositories:

```sh
skeel apply --reinstall tenzir/skills
```

Pinned entries still show up as GitHub-managed skills with source and version metadata after reinstalling. Unpinned entries keep GitHub CLI's default version resolution behavior.

*By @mavam and @codex.*

### Pinned manifest skill updates

`skeel update` now refreshes pinned GitHub skills that are declared in the manifest instead of reporting them as skipped:

```sh
skeel update
```

This keeps pinned sources such as `tenzir/skills` updateable while preserving their GitHub source metadata.

*By @mavam and @codex.*
