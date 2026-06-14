---
title: Reconciled apply workflow
type: change
authors:
  - mavam
created: 2026-06-14T20:20:01.332881Z
---

`skeel apply` now reconciles installed skills with the manifest instead of only installing missing entries.

```sh
skeel apply
skeel apply --dry-run
skeel apply --reinstall
skeel apply --reinstall tenzir/skills
skeel apply tenzir/skills tenzir-docs
```

By default, apply installs missing manifest skills and removes extra skills from the managed directory. Targeted apply limits reconciliation to one source or skill, and `--reinstall` reruns installers without first computing drift.

Dry-run flags now work before or after mutating subcommands, so both `skeel --dry-run apply` and `skeel apply --dry-run` preview commands without changing files. Human output uses concise clypi status lines and spinners while commands run.
