# 🛠️ skeel

Declarative agent skill management.

**skeel** reads a desired-state manifest and applies it through a backend.

The first backend is `gh skill` from GitHub CLI.

## ✨ Features

- **Desired state**: declare skill sources in one YAML file
- **Plan and diff**: preview commands and compare managed skills against what's
  installed locally
- **Apply and update**: install missing skills and update gh-managed skills
- **Target flags**: choose the backend agent and local or global scope from the
  CLI

## 🚀 Quickstart

Run `skeel` directly with `uvx`:

```sh
uvx skeel --help
```

## ⚙️ Manifest

Default path: `~/.agents/skills.yaml`

```yaml
sources:
  - tenzir/skills@tenzir-docs
  - mavam/quarto-brief
  - github: openclaw/gogcli
    skills:
      - gog
```

By default, `skeel` installs backend-managed skills into `.agents/skills` in the
current repository. Use `-g` or `--scope user` for global installs into
`~/.agents/skills`:

```sh
uvx skeel -g apply
```

Use `--agent` to delegate placement to a backend agent:

```sh
uvx skeel --agent claude-code --scope user apply
```

Use `--manifest` (`-m`) for a non-default desired-state manifest:

```sh
uvx skeel --manifest ./skills.yaml plan
```

## ✨ Usage

```sh
uvx skeel plan    # print commands
uvx skeel diff    # compare desired vs installed skills
uvx skeel apply   # install desired state
uvx skeel update  # update installed gh-managed skills
uvx skeel path    # print manifest path
```

For the default target, `diff` compares project scope against `.agents/skills`
in the current repository and global scope against `~/.agents/skills`.

## 🧰 Backend policy

By default, `skeel` delegates placement to `gh skill` with:

```sh
gh skill install <repo> <skill> --dir .agents/skills --force
```

The target directory, agent, and scope come from CLI flags. A bare GitHub source
installs all skills from that repository:

```yaml
sources:
  - mavam/quarto-brief
```

which plans:

```sh
gh skill install mavam/quarto-brief --all --dir .agents/skills --force
```

For installers that are not backed by `gh skill`, provide source-level
`install` commands. In this form, skeel runs those commands as the complete
install plan:

```yaml
sources:
  - skills:
      - clacks
    install:
      - uvx --from slack-clacks clacks skill --mode universal
      - uvx --from slack-clacks clacks skill --mode claude
```

## 📄 License

[MIT](LICENSE)
