This release makes skeel's command output more consistent across project and user scopes. It also improves list, diff, add, and remove feedback so users can see unmanaged skills and pending manifest changes more clearly.

## 🔧 Changes

### Clarify successful skill removal output

The `add` and `remove` commands without `--apply` previously rendered manifest edits with the green success check, which looked identical to `list` output and made it hard to tell that anything changed. They now use the install (`+`) and remove (`-`) glyphs, matching `diff` and `apply`, so a successful add or removal clearly reads as a change.

*By @mavam in #11.*

### Unified skill inventory

The `list` command now shows a unified project and user inventory, including installed skills that are not declared in a manifest:

```sh
skeel list
```

Previously, `list` only displayed manifest entries, so manually installed project or user skills could be hidden from the default view. Human output now shows a single list, and every command renders scope the same way: a muted scope glyph after the action marker (`★` for project, `⌂` for user). Unmanaged installed skills appear alongside managed ones, and JSON output marks them with `"managed": false`.

*By @mavam and @codex in #10.*

## 🐞 Bug fixes

### Dynamic source diff output

The `diff` command now reports dynamic sources that select all skills when they still need to be applied:

```sh
uvx skeel add example/skills
uvx skeel diff
```

This now shows `+ example/skills` instead of producing no output before `apply` installs the source.

*By @mavam and @codex in #9.*
