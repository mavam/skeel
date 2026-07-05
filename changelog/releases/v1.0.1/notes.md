skeel now repairs managed GitHub skills when their provenance metadata is missing or points at a different manifest source. Re-running apply or update after the repair stays idempotent.

## 🐞 Bug fixes

### Metadata repair for managed GitHub skills

`apply` and `update` now repair managed GitHub skills whose provenance is missing or points at a different source by reinstalling from the manifest source:

```sh
skeel apply
skeel update
```

This also works for sources that install all skills from a repository:

```yaml
sources:
  example/skill-catalog:
```

After `gh skill` writes the GitHub metadata, re-running the same command no longer schedules another repair.

*By @mavam in #16.*
