{ pkgs, home-manager }:

let
  mkHome =
    configuration:
    home-manager.lib.homeManagerConfiguration {
      inherit pkgs;
      modules = [
        ./home-manager.nix
        {
          home.username = "test";
          home.homeDirectory = if pkgs.stdenv.hostPlatform.isDarwin then "/Users/test" else "/home/test";
          home.stateVersion = "26.05";
        }
        configuration
      ];
    };
  discovered = mkHome {
    programs.skeel = {
      enable = true;
      targets = [
        ".agents/skills"
        ".claude/skills"
      ];
      # Exercise the outPath coercion used by non-flake inputs.
      sources.upstream.src = {
        outPath = "${./fixtures/upstream}";
      };
    };
  };
  selected = mkHome {
    programs.skeel = {
      enable = true;
      sources.upstream = {
        src = ./fixtures/upstream;
        skills.shorthand = "first";
        skills.renamed = {
          path = "first";
          frontmatter = {
            disable-model-invocation = true;
            metadata.added = "value";
          };
        };
      };
    };
  };
  disabled = mkHome { };
  badTarget = mkHome {
    programs.skeel.enable = true;
    programs.skeel.targets = [ "../escape" ];
  };
  python = pkgs.python314.withPackages (p: [
    p.python-frontmatter
    p.pyyaml
  ]);
in
assert !(disabled.config.home.file ? ".agents/skills");
assert discovered.config.home.file.".agents/skills".recursive;
assert discovered.config.home.file.".claude/skills".recursive;
assert !(builtins.tryEval badTarget.activationPackage.drvPath).success;
pkgs.runCommand "skeel-home-manager-tests"
  {
    nativeBuildInputs = [ python ];
  }
  ''
    discovered=${discovered.config.home.file.".agents/skills".source}
    selected=${selected.config.home.file.".agents/skills".source}
    test -f "$discovered/alpha/SKILL.md"
    test -f "$discovered/beta/SKILL.md"
    test -f "$discovered/alpha/references/example.txt"
    test ! -e "$selected/alpha"
    test ! -e "$selected/beta"
    test -f "$selected/shorthand/SKILL.md"
    python - "$selected/renamed/SKILL.md" <<'PY'
    import frontmatter, sys
    skill = frontmatter.load(sys.argv[1])
    assert skill['name'] == 'renamed'
    assert skill['disable-model-invocation'] is True
    assert skill['metadata'] == {'retained': 'value', 'added': 'value'}
    assert skill.content == 'Fixture body.'
    PY
    # Build real HM links without activating or touching a user's home directory.
    files=${discovered.activationPackage}/home-files
    test -d "$files/.agents/skills"
    test ! -L "$files/.agents/skills"
    test -L "$files/.agents/skills/alpha/SKILL.md"
    test -L "$files/.claude/skills/alpha/SKILL.md"
    touch "$out"
  ''
