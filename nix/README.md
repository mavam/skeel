# Nix and Home Manager

Skeel exposes two independent flake outputs:

- `packages.<system>.default` installs the Skeel CLI with Python 3.14 and GitHub CLI.
- `homeManagerModules.default` builds and installs skills with Home Manager. It
  does not run `skeel`, `gh skill`, or custom installers during activation.

Packages are exposed for `x86_64-linux`, `aarch64-linux`, and `aarch64-darwin`.
The pinned unstable nixpkgs no longer supports Intel macOS.

## Install the CLI

```sh
nix run github:mavam/skeel -- --help
nix profile add github:mavam/skeel
```

The CLI still reads YAML manifests and supports the existing imperative commands.
Custom installers remain responsible for their own executables, such as `uvx`.

## Declare skills with Home Manager

Add Skeel and your skill repositories to your own flake. Your lock file owns
source revisions; Skeel does not resolve Git branches or fetch skills at activation.

```nix
inputs = {
  skeel.url = "github:mavam/skeel";
  skeel.inputs.nixpkgs.follows = "nixpkgs";
  anthropic-skills = {
    url = "github:anthropics/skills";
    flake = false;
  };
  elevenlabs-skills = {
    url = "github:elevenlabs/skills";
    flake = false;
  };
};
```

Include this module in your Home Manager configuration, where `inputs` refers to
those flake inputs:

```nix
{
  imports = [ inputs.skeel.homeManagerModules.default ];

  programs.skeel = {
    enable = true;
    targets = [ ".agents/skills" ".claude/skills" ];
    sources = {
      anthropic = {
        src = inputs.anthropic-skills;
        skills.skill-creator = "skills/skill-creator";
      };
      elevenlabs = {
        src = inputs.elevenlabs-skills;
        skills.elevenlabs-agents = {
          path = "agents";
          frontmatter.disable-model-invocation = true;
        };
      };
    };
  };
}
```

The CLI package is optional and defaults to `null`. To install it alongside native
management, set `programs.skeel.package = inputs.skeel.packages.${pkgs.stdenv.hostPlatform.system}.default`.
Do not use the CLI to update or prune skills owned by Home Manager.

### Sources and selections

- `src` accepts a source directory, including a non-flake input or a store path.
  It can point at a subdirectory to limit discovery.
- `skills = null` (the default) discovers all skills below that source, including
  hidden agent directories. Discovery stops at each directory containing
  `SKILL.md`; it skips `.git`, `.hg`, `.svn`, `.venv`, `node_modules`, and
  `__pycache__` directories.
- Discovered skills use their frontmatter `name`, not their directory name.
- An attribute set selects skills explicitly. Each key is the installed name;
  each value is a relative directory path or an object with `path` and
  `frontmatter`. Use `path = "."` for a skill at the source root.
- `skills = { }` selects nothing from that source.
- Selected names update both the destination directory and the frontmatter name.
  Duplicate names across or within sources fail the build.
- Frontmatter overrides replace top-level fields and shallow-merge `metadata`,
  matching the CLI. They cannot override `name` or `github-*` provenance fields.
  Updating frontmatter normalizes YAML formatting.
- Skills must be self-contained. Symlinks in selected skill trees, escaping
  paths, and invalid skill names fail the build. No source scripts are executed.

### Target directories

Targets are explicit paths relative to the user's home directory:

| Target | Typical consumer |
| --- | --- |
| `.agents/skills` | Shared discovery, including Pi and Codex |
| `.claude/skills` | Claude Code |
| `.codex/skills` | Codex-specific placement |
| `.pi/agent/skills` | Pi-specific placement |

Only add agent-specific targets when needed, to avoid duplicate discovery.
For custom agent configuration directories, supply their corresponding
home-relative paths. The module does not read environment variables to choose
placement or modify any agent settings.

Home Manager recursively links individual files, leaving the target directories
real and writable. It preserves unrelated files and skills. Conflicting existing
files stop activation rather than being overwritten. Skills removed from the
configuration have their managed links removed on the next activation.

### Updates and migration

- Update selected source inputs with `nix flake update <input-name>`, then rebuild
  and activate your Home Manager or nix-darwin configuration.
- Back up and move existing skill directories out of the way before the first
  activation. Preserve undeclared local skills; do not remove the whole shared
  skill directory.
- Managed files are read-only. Skills must keep credentials, caches, and generated
  output outside their managed files. Nix-store contents can be read by other
  local users; do not include secrets in source trees or frontmatter.
- The native module deliberately does not read `skills.yaml`, execute `install:`
  commands, or maintain `gh skill` provenance. Package generated skills separately
  and pass their output directory as a source.
- Import the module only on the desired hosts. It does not assume Darwin-only or
  system-wide installation.

## Development checks

```sh
nix flake check
uv run pytest
```

Flake checks build the CLI, run its Python tests, and exercise discovery,
selection, renaming, frontmatter overrides, and actual Home Manager file links.
