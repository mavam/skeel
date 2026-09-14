---
title: Nix and Home Manager support
type: feature
authors:
  - mavam
prs:
  - 26
created: 2026-09-14T08:09:44.381281Z
---

You can now install Skeel with Nix and manage agent skills natively through Home Manager. The module builds skills from sources pinned by your own flake, supports discovery, selection, renaming, and frontmatter overrides, and leaves unrelated local skills untouched.

```nix
programs.skeel = {
  enable = true;
  sources.anthropic = {
    src = inputs.anthropic-skills;
    skills.skill-creator = "skills/skill-creator";
  };
};
```

Skill installation requires no `gh skill` or custom installer commands during activation. The existing YAML-based CLI remains available independently.
