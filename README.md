# 🛠️ skeel

Declarative agent skill management.

**skeel** reads a desired-state manifest and applies it through `gh skill`.

## ✨ Features

- **Desired state**: declare skill sources in one YAML file
- **Inventory, dry run, and diff**: list selected skill inventory, preview
  commands, and compare managed skills against what's installed locally
- **Add, apply, and update**: edit desired state, reconcile installed skills
  with live progress, and update declared installed skills
- **Target flags**: choose project or user scope, a specific agent's skill
  directory, or any explicit directory from the CLI
- **JSON output**: pass `--json` for one machine-readable object on stdout

## 🚀 Quickstart

Run `skeel` directly with `uvx`:

```sh
uvx skeel
```

## ⚙️ Manifest

Default path: `.agents/skills.yaml` in project scope, `~/.agents/skills.yaml`
in user scope.

```yaml
sources:
  anthropics/skills:
    - skill-creator
  mavam/quarto-brief:
  openclaw/gogcli:
    - gog
  tenzir/skills:
    pin: main
    skills:
      - tenzir-ecs
```

An empty value installs all skills from a source. A list is the common form for
selected skills. Use a nested mapping only for source options, such as `pin` or
custom `install` commands. During `update`, selected skills refresh independently,
while an install-all source refreshes once and discovers newly added upstream
skills.

By default, `skeel` uses project scope: `.agents/skills.yaml` and
`.agents/skills` in the current working directory. Use `-g` or `--scope user`
for global installs into
`~/.agents/skills`:

```sh
uvx skeel -g apply
```

Use `--manifest` (`-m`) for a non-default desired-state manifest:

```sh
uvx skeel --manifest ./skills.yaml apply --dry-run
```

Scope selects the base directory for the implicit manifest and managed skill
directory: project scope uses the current working directory and user scope uses
`$HOME`. Use `-a` or `--all` with commands that can operate on both scopes. If
the implicit manifest does not exist, `apply`, `diff`, `list`, and `update` are
no-ops; `add` creates the manifest. Use `--manifest` or `SKEEL_MANIFEST` to use
a manifest from another path. Because an explicit manifest path is not scoped,
`-a` and `--all` are rejected when `--manifest` or `SKEEL_MANIFEST` is set.

## 🎯 Agent Targets

By default, skeel manages the universal `.agents/skills` directory. Use
`--agent` to manage a specific agent's skill directory instead, or `--dir` for
an explicit directory:

```sh
uvx skeel --agent claude-code apply
uvx skeel --agent codex apply
uvx skeel --agent pi -g list
uvx skeel --dir ./custom/skills list
```

Agent names and directories mirror the GitHub CLI host registry. List them
with:

```sh
uvx skeel agents
```

For an agent-specific target, project scope anchors at the enclosing git
repository root so skills land where the agent discovers them, falling back to
the working directory outside a repository. The `universal` target retains the
default current-directory anchoring and project-over-user shadowing behavior.
Manifests stay agent-neutral: the same `.agents/skills.yaml` drives every target.
Agent-specific targets reconcile project and user scope independently; when the
same skill appears in both, skeel warns and lets the agent decide runtime
precedence. `--dir` is a complete target on its own and cannot be combined with
`--agent` or scope selectors.

Custom `install:` commands receive `SKEEL_AGENT`, `SKEEL_SCOPE`,
`SKEEL_SKILLS_DIR`, and `SKEEL_MANIFEST` in their environment. `SKEEL_AGENT`
is `universal` for the default target, the selected agent ID for `--agent`, and
empty for `--dir`. Portable installers must honor `SKEEL_SKILLS_DIR`; skeel
verifies that declared skills appear there and fails the step otherwise.

## ✨ Commands

By default, every command operates on project scope. Use `-g`, `--user`,
`--global`, or `--scope user` to operate on user scope. Use `-a` or `--all` to
operate on both project and user scopes for `diff`, `list`, `apply`, `remove`,
and `update` when using the implicit manifests.

Human output is consistent across commands: the first column is the action
marker, the second column is a muted scope glyph (`★` for project, `⌂` for
user), followed by the skill name, the source, and a muted suffix for versions,
paths, or diagnostic details.

For scripts, pass `--json` to `add`, `apply`, `diff`, `list`, `path`, `remove`,
or `update` to emit one machine-readable object on stdout.

### `list`

Show installed skills together with manifest status. Missing manifest skills
are marked with `✘`; installed skills that are not declared in the manifest
still appear in the inventory and include `"managed": false` in JSON output.
Rows are tagged with their scope glyph. Sources declared without a skill list
expand to the installed skills from that source instead of showing `*`.

```sh
uvx skeel list -a
```

```text
✔︎ ★ tenzir-docs tenzir/skills main@a5d04ab
✘ ★ gog openclaw/gogcli
✔︎ ⌂ skill-creator anthropics/skills main@3cf9a8d
✔︎ ⌂ wrangler cloudflare/skills main@45cc198
✔︎ ⌂ clacks
✔︎ ⌂ quarto-brief mavam/quarto-brief main@e89c555
```

### `diff`

Compare desired state with installed skills. `+` rows would be installed by
`apply`; `-` rows would be removed by `apply --prune`.

```sh
uvx skeel diff
```

```text
+ ★ wrangler cloudflare/skills
+ ★ vectorize cloudflare/skills
- ★ obsolete-skill installed
- ★ old-experiment installed
```

### `apply`

Reconcile installed skills with the manifest. Missing skills are installed;
skills not declared in the manifest are preserved by default. Pass `--prune`
to also remove undeclared extras. Pruning applies only to a full reconciliation;
combine neither `--reinstall` nor a source selector with `--prune`. Use
`--reinstall` to run every manifest installer without diffing first, or
`apply <source> [skill]` to target one source. A selector that does not match
the manifest exits with an error.

```sh
uvx skeel apply --dry-run --prune
```

```text
↳ gh skill install cloudflare/skills wrangler --allow-hidden-dirs --dir .agents/skills --force
↳ gh skill install cloudflare/skills vectorize --allow-hidden-dirs --dir .agents/skills --force
↳ rm -rf .agents/skills/obsolete-skill
```

```sh
uvx skeel apply --prune
```

```text
+ ★ wrangler cloudflare/skills
+ ★ vectorize cloudflare/skills
- ★ obsolete-skill
```

Immediately before deleting anything, skeel verifies that the planned target
and skill directories have not been replaced, requires a regular `SKILL.md`
inside the target, refuses symlinked skills and paths outside the target, and
never removes the target root. A target directory itself may be reached through
a symlink; skeel pins its resolved destination while planning. These safeguards
also cover skills pruned from pinned install-all sources during `update`.

### `update`

Update installed skills that are represented by the manifest. Explicit skill
entries update independently, and remote update checks run in parallel. An
install-all entry refreshes once at source level, including when it uses a branch
pin such as `main`. This refresh also installs skills added to the upstream
source since the previous update.

Pass a source, or a source and skill, to update only that manifest selection. A
source-and-skill selector stays targeted to that skill, even when the manifest
entry normally installs all skills. A selector that does not match the manifest
exits with an error.

```sh
uvx skeel update
uvx skeel update tenzir/skills
uvx skeel update tenzir/skills tenzir-docs
uvx skeel update -a
```

```text
✔︎ ★ teach mattpocock/skills main@975430f
✔︎ ★ tenzir-docs tenzir/skills main@f3842c1
✔︎ ★ clacks downstairs-dawgs/clacks
✘ ★ broken-skill broken/source
```

Pinned GitHub entries are updated by resolving the configured pin and
refreshing installed files when the source changes. Branch pins are checked for
new content. Immutable tag and commit pins report `current` when their recorded
tree is unchanged, without downloading the same archive again. Skills installed
by `gh skill` include provenance in `SKILL.md` frontmatter, so future updates can
track them directly.

Updates for pinned install-all sources also prune skills removed upstream. Skeel
deletes a directory only when its `github-repo` matches the source exactly and
its `github-path` is absent from the source's current inventory. Metadata-less,
malformed, and differently owned directories stay untouched. The source-level
result names removed skills, and JSON output includes their paths.

A dry run resolves a pinned source and previews each removal without changing
local files. Unpinned install-all sources still add and refresh skills without
pruning because `gh skill install --all` doesn't expose the remote inventory.
Use `apply --reinstall` when you need to force-refresh an install-all entry
without pruning it.

### `add`

Upsert a source or source/skill entry into the manifest. Omit the skill to
select all skills from the source. Pass `--apply` to reconcile immediately.

```sh
uvx skeel add tenzir/skills tenzir-docs@main
```

```text
✔︎ ★ tenzir-docs tenzir/skills .agents/skills.yaml
```

```sh
uvx skeel add mavam/quarto-brief --dry-run
```

```text
↳ mavam/quarto-brief .agents/skills.yaml
```

### `remove`

Remove an unambiguous skill name from the selected manifest. Pass `--apply` to
reconcile immediately; this deletes exactly the deselected skill and leaves
other undeclared skills alone. A selector that does not match the manifest
exits with an error.

`add` and `remove` are intentionally asymmetric: adding starts from a source
because skeel needs to know where to install from, while removing starts from a
skill because that is the common user intent. Use `--source` only to
disambiguate or remove a whole source.

```sh
uvx skeel remove tenzir-docs
```

```text
✔︎ ★ tenzir-docs tenzir/skills .agents/skills.yaml
```

When multiple sources declare the same skill name, disambiguate with `--source`:

```sh
uvx skeel remove tenzir-docs --source tenzir/skills
```

Omit the skill to remove the whole source selected by `--source`. For custom
installers, list every produced skill under `skills:` so `--apply` can identify
the directories safely:

```sh
uvx skeel remove --source mavam/quarto-brief --dry-run
```

```text
↳ mavam/quarto-brief .agents/skills.yaml
```

### `agents`

List supported agents with their project and user skill directories. JSON
output uses absolute user paths. Claude Code's user directory reflects
`CLAUDE_CONFIG_DIR` when the variable is set; `~` expands to the home directory,
and relative values are anchored there.

```sh
uvx skeel agents
```

```text
github-copilot   .agents/skills   ~/.copilot/skills
claude-code      .claude/skills   ~/.claude/skills
codex            .agents/skills   ~/.codex/skills
cursor           .agents/skills   ~/.cursor/skills
pi               .pi/skills       ~/.pi/agent/skills
...
```

### `path`

Print the manifest path that `skeel` would use for the selected scope.

```sh
uvx skeel path
```

```text
.agents/skills.yaml
```

Use `-a` to print both implicit paths:

```sh
uvx skeel path -a
```

```text
project .agents/skills.yaml
user    /Users/alice/.agents/skills.yaml
```

## 🧰 GitHub Skill Policy

When applying, `skeel` delegates placement to `gh skill` with:

```sh
gh skill install <repo> <skill> --dir .agents/skills --force
```

The target directory is derived from scope: project scope uses the current
working directory and user scope uses `$HOME`. A bare GitHub source installs all
skills from that repository:

```yaml
sources:
  mavam/quarto-brief:
```

which runs:

```sh
gh skill install mavam/quarto-brief --all --dir .agents/skills --force
```

For installers that are not backed by `gh skill`, provide source-level
`install` commands under the source key. Skeel runs those commands as the
complete install command set:

```yaml
sources:
  slack-clacks/clacks:
    skills:
      - clacks
    install:
      - uvx --from slack-clacks clacks skill --mode universal --force
```

To add a GitHub source from the CLI, use the same positional shape as
`gh skill install`:

```sh
uvx skeel add tenzir/skills tenzir-docs@main
uvx skeel remove tenzir/skills tenzir-docs
uvx skeel add mavam/quarto-brief --apply
```

## 📄 License

[MIT](LICENSE)
