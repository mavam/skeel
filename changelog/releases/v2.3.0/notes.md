Manage agent skills natively with Nix and Home Manager using pinned sources, declarative selections, and frontmatter overrides. This release also lets you install skills under custom local names.

## 🚀 Features

### Nix and Home Manager support

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

*By @mavam in #26.*
