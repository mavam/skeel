---
title: Skill frontmatter overrides
type: feature
authors:
  - mavam
prs:
  - 24
created: 2026-08-26T05:10:33.92072Z
---

You can now override `SKILL.md` frontmatter for explicitly selected skills. Skeel applies the overrides during installation, restores them after updates, and reconciles later manifest changes:

```yaml
sources:
  owner/skills:
    skills:
      - name: deploy
        frontmatter:
          disable-model-invocation: true
```

This lets you keep upstream skills user-invocable without allowing Claude Code to load them automatically.
