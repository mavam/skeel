---
title: Skill frontmatter overrides
type: feature
authors:
  - mavam
prs:
  - 24
created: 2026-08-26T05:10:33.92072Z
---

You can now customize an explicitly selected skill's frontmatter in the manifest. Skeel applies configured fields during installation and updates, and reconciles later drift:

```yaml
sources:
  owner/skills:
    skills:
      - name: deploy
        frontmatter:
          compatibility: Requires Docker
          disable-model-invocation: true
```

Top-level values replace their upstream counterparts, while `metadata` entries merge with existing metadata. The `diff` command reports configured values that haven't been applied yet.
