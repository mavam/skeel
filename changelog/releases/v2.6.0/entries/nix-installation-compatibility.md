---
title: Nix installation compatibility
type: bugfix
authors:
  - mavam
prs:
  - 30
created: 2026-10-21T07:48:18.214502Z
---

Nix installations no longer fail with a `makeWrapper` argument error when using current nixpkgs. The packaged CLI still finds GitHub CLI and Git without requiring them on your existing `PATH`.
