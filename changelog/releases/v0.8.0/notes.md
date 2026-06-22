This release makes skeel update output easier to scan and more reliable across project and user scopes. It also fixes non-interactive GitHub skill updates and avoids duplicate unscoped update checks from the home directory.

## 🔧 Changes

### Quieter output for up-to-date skills

`skeel update` no longer repeats the version label for skills that are already up to date. Unchanged skills render without version noise, so the output highlights only what actually changed.

*By @mavam and @claude in #6.*

### Scope indicator across all commands

`skeel` now shows the `⌂` user-scope indicator in every command that can span both the project and user manifests — `list`, `update`, `apply`, `remove`, and `diff` — so you can always tell which scope a skill belongs to:

```sh
skeel diff
+ tenzir-docs tenzir/skills
+ wrangler cloudflare/skills ⌂
```

The `diff` JSON output gains a matching `scope` field on every entry.

*By @mavam and @claude in #6.*

## 🐞 Bug fixes

### Duplicate unscoped skill updates from home

Unscoped `skeel update` no longer runs the same user manifest twice when invoked from `$HOME`.

For example:

```sh
cd ~
uvx skeel update
```

When the default project and user paths both resolve to `~/.agents`, each installed skill is now checked and reported once.

*By @mavam and @codex in #5.*

### Non-interactive skill updates

`skeel update` now applies available GitHub skill updates in non-interactive runs instead of failing with a confirmation prompt from `gh skill`.

For example:

```sh
uvx skeel update
```

When a declared skill has an update, the command updates it directly and keeps reporting per-skill results.

*By @mavam and @codex in #7.*
