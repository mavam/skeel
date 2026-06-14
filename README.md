# 🛠️ skeel

Declarative agent skill management.

**skeel** reads a desired-state manifest and applies it through `gh skill`.

## ✨ Features

- **Desired state**: declare skill sources in one YAML file
- **Inventory, dry run, and diff**: list manifest skill status, preview
  commands, and compare managed skills against what's installed locally
- **Add, apply, and update**: edit desired state, reconcile installed skills
  with clypi spinners, and update declared installed skills
- **Target flags**: choose local or global scope from the CLI
- **JSON output**: pass `--json` for one machine-readable object on stdout

## 🚀 Quickstart

Run `skeel` directly with `uvx`:

```sh
uvx skeel --help
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

By default, `skeel` installs `gh skill` skills into `.agents/skills` in the
current working directory. Use `--scope user` for global installs into
`~/.agents/skills`:

```sh
uvx skeel --scope user apply
```

Use `--manifest` (`-m`) for a non-default desired-state manifest:

```sh
uvx skeel --manifest ./skills.yaml apply --dry-run
```

Scope selects the base directory for the implicit manifest and managed skill
directory: project scope uses the current working directory and user scope uses
`$HOME`. If the implicit manifest does not exist, `apply`, `diff`, `list`, and
`update` are no-ops; `add` creates the manifest. Use `--manifest` or
`SKEEL_MANIFEST` to use a manifest from another path.

## ✨ Usage

```sh
uvx skeel apply              # reconcile desired state
uvx skeel apply --dry-run    # print reconciliation commands
uvx skeel apply --reinstall  # reinstall every manifest entry
uvx skeel apply --reinstall tenzir/skills
uvx skeel add tenzir/skills tenzir-docs@main
uvx skeel remove tenzir/skills tenzir-docs
uvx skeel add mavam/quarto-brief --apply
uvx skeel update             # update installed manifest skills
uvx skeel list               # show manifest skill status
uvx skeel diff               # compare desired vs installed skills
uvx skeel path               # print manifest path
```

For scripts, use `--json`:

```sh
uvx skeel --json apply --dry-run
uvx skeel --json add tenzir/skills tenzir-docs
uvx skeel --json remove tenzir/skills tenzir-docs
uvx skeel --json list
uvx skeel --json diff
uvx skeel --json update --dry-run
```

`list` shows every skill entry from the manifest and whether it is installed.
By default, `list`, `diff`, `apply`, and `update` read both
`.agents/skills.yaml` in the current working directory and
`~/.agents/skills.yaml`; use `--scope project` or `--scope user` to operate on
one scope.

For the default target, `diff` compares project scope against `.agents/skills`
in the current working directory and user scope against `~/.agents/skills`.
`apply` uses the same comparison to install missing skills and remove extra
installed skills. Use `apply --reinstall` to run every manifest installer
without reconciling first. Pass `apply <source> [skill]` to limit the operation
to one manifest source; targeted apply installs missing selected entries and
leaves unrelated installed skills alone.

`add <source> [skill@version]` upserts desired state into the manifest. Omitting
the skill selects all skills from the source. `remove <source> [skill]` removes
the selected skill or the whole source when the skill is omitted. Pass `--apply`
to either command to update the manifest and immediately reconcile installed
skills.

`update` checks each installed skill separately. Human output uses the leading
marker as the status:

- `✔` updated the skill. When provenance is available, the muted suffix shows
  the local version before and after the update, such as `main@oldsha →
  main@newsha`.
- `•` checked the skill and it is already current.
- `→` skipped the skill. The skill is installed and available locally, but was
  not updated. This usually means the installed `SKILL.md` has no GitHub
  metadata, or the skill is pinned, so `gh skill` cannot update it
  automatically.

Skills installed by `gh skill` include provenance in `SKILL.md` frontmatter, and
future updates can track them directly.

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
