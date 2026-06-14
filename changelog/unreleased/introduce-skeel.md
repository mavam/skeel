---
title: Introduce skeel
type: feature
authors:
  - mavam
created: 2026-06-14T10:31:24.200296Z
---

Introduced `skeel`, a Python 3.14 CLI for managing agent skills from a desired-state YAML manifest.

Quickstart:

1. Run the CLI directly:

   ```sh
   uvx skeel --help
   ```

2. Create `~/.agents/.skill.yaml` with a shared skill directory, target agents, and GitHub skill sources:

   ```yaml
   version: 1
   shared_dir: ~/.agents/skills
   agents:
     - universal
     - claude-code
   sources:
     - source: mavam/skills
       skills:
         - mavam
     - source: openclaw/gogcli
       allow_hidden_dirs: true
       skills:
         - gog
   ```

3. Preview the desired changes:

   ```sh
   uvx skeel plan
   uvx skeel diff
   ```

4. Apply and maintain the configured skills:

   ```sh
   uvx skeel apply
   uvx skeel update
   ```

`skeel` installs skills through `gh skill install` into the shared directory and links them into agent-specific locations such as `~/.claude/skills` for Claude Code.
