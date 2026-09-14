{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.programs.skeel;
  json = pkgs.formats.json { };
  selection = lib.types.submodule (
    { name, ... }: {
      options = {
        path = lib.mkOption {
          type = lib.types.str;
          default = name;
          description = "Skill directory relative to its source. Use a full relative path, or . for a root skill.";
        };
        frontmatter = lib.mkOption {
          type = json.type;
          default = { };
          description = "Top-level frontmatter overrides. Metadata is shallow-merged; name is set by the selection key.";
        };
      };
    }
  );
  python = pkgs.python314.withPackages (p: [
    p.python-frontmatter
    p.pyyaml
  ]);
  specifications = json.generate "skeel-sources.json" (
    lib.mapAttrs (_: source: {
      src = "${source.src}";
      inherit (source) skills;
    }) cfg.sources
  );
  skills =
    pkgs.runCommand "skeel-skills"
      {
        nativeBuildInputs = [ python ];
      }
      ''
        export PYTHONPATH=${../src}
        python -m skeel.nix_build ${specifications} "$out"
      '';
  validTarget =
    target:
    target != ""
    && !(lib.hasPrefix "/" target)
    && builtins.match ".*[\n\r].*" target == null
    && lib.all (part: part != "" && part != "." && part != "..") (lib.splitString "/" target);
in
{
  options.programs.skeel = {
    enable = lib.mkEnableOption "declarative, build-time agent skill installation";
    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = null;
      description = "Optional Skeel CLI package. Native skill installation does not need the CLI or gh at activation time.";
    };
    targets = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ".agents/skills" ];
      example = [
        ".agents/skills"
        ".claude/skills"
      ];
      description = "Skill directories relative to the home directory. Use agent-specific paths or custom directories as needed.";
    };
    sources = lib.mkOption {
      default = { };
      description = "Pinned source trees supplied by the caller, usually non-flake inputs. Attribute names are diagnostic labels.";
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            src = lib.mkOption {
              type = lib.types.path;
              description = "Source directory containing skills. Source fetching and revision pinning belong to the caller.";
            };
            skills = lib.mkOption {
              type = lib.types.nullOr (
                lib.types.attrsOf (lib.types.coercedTo lib.types.str (path: { inherit path; }) selection)
              );
              default = null;
              example = {
                elevenlabs-agents = "skills/agents";
              };
              description = "Selected skills keyed by installed name. Null discovers all skills using their frontmatter names; an empty set selects none.";
            };
          };
        }
      );
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.targets != [ ] && lib.all validTarget cfg.targets;
        message = "programs.skeel.targets must contain nonempty home-relative paths without . or .. components.";
      }
    ];
    home.packages = lib.optional (cfg.package != null) cfg.package;
    # Home Manager links individual files and keeps target directories writable.
    # Unmanaged skills are not pruned or replaced.
    home.file = lib.genAttrs (lib.unique cfg.targets) (_: {
      source = skills;
      recursive = true;
    });
  };
}
