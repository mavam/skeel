skeel introduces a Python 3.14 CLI for managing agent skills from a desired-state YAML manifest. Users can preview, apply, and update GitHub-hosted skills across shared and agent-specific directories with one workflow.

## 🚀 Features

### Introduce skeel

Introduced `skeel`, a Python 3.14 CLI for managing agent skills from a desired-state YAML manifest.

Quickstart:

1. Run the CLI directly:

   ```sh
   uvx skeel --help
   ```

1. Create `~/.agents/.skill.yaml` with a shared skill directory, target agents, and GitHub skill sources:

   ```yaml
   version: 1
   shared_dir: ~/.agents/skills
   agents:
     - universal
     - claude-code
   sources:
     - source: tenzir/skills
       skills:
         - tenzir-docs
     - source: openclaw/gogcli
       allow_hidden_dirs: true
       skills:
         - gog
   ```

1. Preview the desired changes:

   ```sh
   uvx skeel plan
   uvx skeel diff
   ```

1. Apply and maintain the configured skills:

   ```sh
   uvx skeel apply
   uvx skeel update
   ```

`skeel` installs skills through `gh skill install` into the shared directory and links them into agent-specific locations such as `~/.claude/skills` for Claude Code.

*By @mavam.*
