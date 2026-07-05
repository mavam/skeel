---
title: Metadata repair for managed GitHub skills
type: bugfix
authors:
  - mavam
prs:
  - 16
created: 2026-07-05T11:41:05.663927Z
---

`apply` and `update` now repair managed GitHub skills whose provenance is missing or points at a different source by reinstalling from the manifest source:

```sh
skeel apply
skeel update
```

After `gh skill` writes the GitHub metadata, re-running the same command no longer schedules another repair.
