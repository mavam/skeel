# 🛠️ skeel

Declarative agent skill management.

**skeel** reads a desired-state manifest and applies it through `gh skill`.

## ✨ Features

- **Desired state**: declare skill sources in one YAML file
- **Inventory, dry run, and diff**: list selected skill inventory, preview
  commands, and compare managed skills against what's installed locally
- **Add, apply, and update**: edit desired state, reconcile installed skills
  with live progress, and update declared installed skills
- **Target flags**: choose local or global scope from the CLI
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
custom `install` commands.

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
`apply`; `-` rows would be removed.

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

Reconcile installed skills with the manifest. Missing skills are installed and
extra skills are removed. Use `--reinstall` to run every manifest installer
without diffing first, or `apply <source> [skill]` to target one source. A
selector that does not match the manifest exits with an error.

```sh
uvx skeel apply --dry-run
```

```text
↳ gh skill install cloudflare/skills wrangler --allow-hidden-dirs --dir .agents/skills --force
↳ gh skill install cloudflare/skills vectorize --allow-hidden-dirs --dir .agents/skills --force
↳ rm -rf .agents/skills/obsolete-skill
```

```sh
uvx skeel apply
```

```text
+ ★ wrangler cloudflare/skills
+ ★ vectorize cloudflare/skills
- ★ obsolete-skill
```

### `update`

Update installed skills that are represented by the manifest. Each installed
skill is checked independently, and remote update checks run in parallel. Pass a
source, or a source and skill, to update only that manifest selection. A selector
that does not match the manifest exits with an error.

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
refreshing installed files when the source changes. Skills installed by
`gh skill` include provenance in `SKILL.md` frontmatter, so future updates can
track them directly.

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
reconcile immediately. A selector that does not match the manifest exits with an
error.

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

Omit the skill to remove the whole source selected by `--source`:

```sh
uvx skeel remove --source mavam/quarto-brief --dry-run
```

```text
↳ mavam/quarto-brief .agents/skills.yaml
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
