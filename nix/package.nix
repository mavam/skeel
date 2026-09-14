{
  lib,
  python314Packages,
  fetchurl,
  gh,
  git,
}:

let
  py = python314Packages;
  project = builtins.fromTOML (builtins.readFile ../pyproject.toml);
  lock = builtins.fromTOML (builtins.readFile ../uv.lock);
  clypiSpec = lib.findFirst (
    p: p.name == "clypi"
  ) (throw "clypi is missing from uv.lock") lock.package;
  clypi =
    py.clypi or (py.buildPythonPackage {
      pname = "clypi";
      inherit (clypiSpec) version;
      pyproject = true;
      src = fetchurl {
        inherit (clypiSpec.sdist) url;
        sha256 = lib.removePrefix "sha256:" clypiSpec.sdist.hash;
      };
      # Use nixpkgs' build backend instead of upstream's exact development pin.
      postPatch = ''
        substituteInPlace pyproject.toml --replace-fail 'hatchling==1.27.0' 'hatchling'
      '';
      build-system = [ py.hatchling ];
      dependencies = [
        py.python-dateutil
        py.typing-extensions
      ];
      pythonImportsCheck = [ "clypi" ];
    });
in
py.buildPythonApplication {
  pname = "skeel";
  inherit (project.project) version;
  pyproject = true;
  src = lib.cleanSource ../.;
  build-system = [ py.hatchling ];
  dependencies = [
    clypi
    py.python-frontmatter
    py.pyyaml
    py.rich
  ];
  nativeCheckInputs = [ py.pytestCheckHook ];
  pythonImportsCheck = [
    "skeel"
    "skeel.cli"
  ];
  makeWrapperArgs = [
    "--suffix PATH : ${
      lib.makeBinPath [
        gh
        git
      ]
    }"
  ];

  meta = {
    description = project.project.description;
    homepage = "https://github.com/mavam/skeel";
    license = lib.licenses.mit;
    mainProgram = "skeel";
    platforms = lib.platforms.unix;
  };
}
