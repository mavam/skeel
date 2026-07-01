This release makes project-scoped skill management the default, improves scoped updates, and clarifies behavior when project skills shadow global skills. It also adds CLI help examples and cleans up interrupt handling so agents and people get clearer guidance and quieter shutdowns.

## 💥 Breaking changes

### Project scope as the default

Scope selection now defaults to project scope for every command. Commands that previously operated on project and user scopes by default now require `-a` or `--all` for the same broad behavior.

Before:

```sh
skeel update
```

After:

```sh
skeel update -a
```

Use `-g`, `--user`, `--global`, or `--scope user` to operate only on the user/global scope:

```sh
skeel update -g
```

*By @mavam and @codex in #13.*

## 🔧 Changes

### CLI help examples

`skeel --help` and every `skeel <command> --help` page now include focused examples:

```sh
skeel apply --dry-run
skeel add owner/repo skill-name
```

This makes the CLI more useful as inline documentation for people and agents exploring available workflows.

*By @mavam and @codex in #14.*

## 🐞 Bug fixes

### Graceful interrupt shutdown

`skeel` now shuts down cleanly when interrupted with `Ctrl+C`:

```sh
skeel update
```

Interrupted runs terminate child commands and suppress cleanup-time `KeyboardInterrupt` tracebacks from temporary-file finalizers, so users see the normal `interrupted` message instead of Python internals.

*By @mavam and @codex in #12.*

### Project skill shadowing for global conflicts

Project-scoped skills now take precedence over user/global skills with the same name when both scopes are selected:

```sh
skeel apply -a
```

When a conflict occurs, `skeel` warns that the user/global skill was skipped and continues with the project-local skill. JSON output includes a `warnings` array so automation can see the same shadowing decision without parsing stderr.

*By @mavam and @codex in #15.*

### Unified scoped skill updates

The `update` command now schedules project- and user-scoped skills in one continuous run when both scopes are selected:

```sh
skeel update -a
```

This keeps live progress continuous instead of completing one scope before starting the next.

*By @mavam and @codex in #12 and #13.*
