# 🛠️ skeel

Declarative agent skill management.

**skeel** reads a desired-state manifest and applies it through a backend.

The first backend is `gh skill` from GitHub CLI.

## ✨ Features

- **Desired state**: declare skills, sources, shared install directory, and
  target agents in one YAML file
- **Plan and diff**: preview commands and compare managed skills against what's
  installed locally
- **Apply and update**: install missing skills and update gh-managed skills
- **Agent links**: installs once into a shared directory and links skills into
  agent-specific locations such as Claude Code

## 🚀 Quickstart

Run `skeel` directly with `uvx`:

```sh
uvx skeel --help
```

## ⚙️ Manifest

Default path: `~/.agents/.skill.yaml`

```yaml
version: 1
shared_dir: ~/.agents/skills
agents:
  - universal
  - claude-code
sources:
  - source: openclaw/gogcli
    allow_hidden_dirs: true
    skills:
      - gog
```

## ✨ Usage

```sh
uvx skeel plan    # print commands
uvx skeel diff    # compare desired vs installed skills
uvx skeel apply   # install desired state
uvx skeel update  # update installed gh-managed skills
uvx skeel path    # print manifest path
```

## 🧰 Backend policy

By default, `skeel` installs each skill into the shared directory with:

```sh
gh skill install <repo> <skill> --dir ~/.agents/skills --force
```

For `claude-code`, it creates symlinks from `~/.claude/skills/<skill>` to the
shared skill directory.

For installers that are not backed by `gh skill`, provide source-level
`install` commands. In this form, skeel runs those commands as the complete
install plan and does not create additional agent links:

```yaml
sources:
  - source: downstairs-dawgs/clacks
    skills:
      - clacks
    install:
      - uvx --from slack-clacks clacks skill --mode universal
      - uvx --from slack-clacks clacks skill --mode claude
```

## 📄 License

[MIT](LICENSE)
