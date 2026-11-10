Skeel now refreshes custom-installed skills and shows clearer, agent-focused update results. This release also fixes Nix installation compatibility with current nixpkgs.

## 🔧 Changes

### Clearer multi-target update output

Updates across multiple installation directories now collapse identical results into one row with muted target names instead of repeating the same skill. For example, `skeel update -g` with universal and Claude Code targets can show:

```text
↑ ⌂ rex  custom installer  universal, claude-code
```

Output identifies the agents receiving each update without repeating installation paths or printing a directory legend. Aligned skill, source, status, and agent columns replace ragged labels. Scope glyphs distinguish project and user installs of the same agent; custom `--dir` targets still show their path. Bold skill names, cyan sources, status colors, and muted targets establish a visual hierarchy without brackets or middle-dot separators. Different outcomes and failures remain separate. Narrow terminals stack secondary fields, and the output remains readable without color.

Pinned skills now use a neutral `=` marker rather than a warning. A single summary line starts with the agent names and distinguishes intentional pinned skips from other skipped updates, for example: `universal, claude-code: 32 up to date, 6 skipped (pinned)`. The same format works for a single agent without a redundant operation total.

Execution progress and apply results also identify the agent. JSON retains separate execution steps with `directory` and, for known agents, `agent`.

*By @mavam in #31.*

## 🐞 Bug fixes

### Custom installer updates

`skeel update` now refreshes skills with custom `install` commands instead of skipping them with a missing GitHub metadata warning:

```sh
skeel update -g rex
```

The installer runs once per target, with the same environment as `apply`. Selecting one skill refreshes the whole custom source. Commands run in order and stop on failure, while unchanged files report `current`.

*By @mavam in #31.*

### Nix installation compatibility

Nix installations no longer fail with a `makeWrapper` argument error when using current nixpkgs. The packaged CLI still finds GitHub CLI and Git without requiring them on your existing `PATH`.

*By @mavam in #30.*
