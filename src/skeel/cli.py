from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator

from . import __version__
from .backends import (
    BackendOptions,
    InstallStep,
    Runner,
    desired_skill_names,
    get_backend,
    installed_skill_names,
    manual_install_steps,
    quote_command,
)
from .manifest import Manifest, load_manifest, manifest_path


def use_color() -> bool:
    return os.environ.get("NO_COLOR") is None


def red(text: str) -> str:
    return f"\033[31m{text}\033[0m" if use_color() else text


def green(text: str) -> str:
    return f"\033[32m{text}\033[0m" if use_color() else text


def diff_sets(manifest: Manifest, options: BackendOptions) -> tuple[list[str], list[str]]:
    desired = desired_skill_names(manifest)
    installed = installed_skill_names(options)
    extra = set() if manifest.has_dynamic_sources else installed - desired
    return sorted(desired - installed), sorted(extra)


def print_diff(manifest: Manifest, options: BackendOptions, *, warning: bool = False) -> bool:
    missing, extra = diff_sets(manifest, options)
    if not missing and not extra:
        return False
    if warning:
        print(f"⚠️  Installed skills differ from {manifest.path}:", file=sys.stderr)
    for name in missing:
        print(red(f"- {name}"), file=sys.stderr)
    for name in extra:
        print(green(f"+ {name}"), file=sys.stderr)
    return True


def iter_install_plan(manifest: Manifest, options: BackendOptions) -> Iterator[InstallStep]:
    for source in manifest.sources:
        if source.install:
            yield from manual_install_steps(source)
            continue
        backend = get_backend(source.backend)
        yield from backend.install_steps(source, options)


def command_plan(manifest: Manifest, options: BackendOptions) -> int:
    for step in iter_install_plan(manifest, options):
        print(quote_command(step.command))
    return 0


def command_diff(manifest: Manifest, options: BackendOptions) -> int:
    return 1 if print_diff(manifest, options) else 0


def command_apply(manifest: Manifest, options: BackendOptions, *, dry_run: bool = False) -> int:
    print_diff(manifest, options, warning=True)
    runner = Runner(dry_run=dry_run)
    action = "Would install" if dry_run else "Installing"
    for source in manifest.sources:
        if source.install:
            for step in manual_install_steps(source):
                print(f"📦 {action} {step.label}…")
                runner.run(step)
            continue
        backend = get_backend(source.backend)
        for step in backend.install_steps(source, options):
            print(f"📦 {action} {step.label}…")
            runner.run(step)
    print("✅ Dry run complete." if dry_run else "✅ Skills applied.")
    return 0


def command_update(manifest: Manifest, options: BackendOptions, *, dry_run: bool = False) -> int:
    print_diff(manifest, options, warning=True)
    runner = Runner(dry_run=dry_run)
    backends = {source.backend for source in manifest.sources if not source.install}
    print("🧠 Would update skills…" if dry_run else "🧠 Updating skills…")
    for backend_name in sorted(backends):
        backend = get_backend(backend_name)
        for step in backend.update_steps():
            runner.run(step, keep_going=True)
    print("✅ Dry run complete." if dry_run else "✅ Skills updated.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Declarative agent skill manager")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--manifest",
        "-m",
        help="Skill manifest path (default: ~/.agents/skills.yaml)",
    )
    parser.add_argument(
        "--agent",
        help="Target agent passed to backend-managed installs; omitted uses .agents/skills",
    )
    parser.add_argument(
        "--scope",
        choices=["project", "user"],
        help="Target install scope passed to backend-managed installs (default: project)",
    )
    parser.add_argument(
        "-g",
        "--global",
        dest="global_scope",
        action="store_true",
        help="Install at user scope; equivalent to --scope user",
    )
    dry_run = argparse.ArgumentParser(add_help=False)
    dry_run.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Print commands without applying changes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    subparsers = parser.add_subparsers(dest="command")
    for name in ["path", "plan", "diff"]:
        subparsers.add_parser(name)
    for name in ["apply", "sync", "update"]:
        subparsers.add_parser(name, parents=[dry_run])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "plan"
    dry_run = getattr(args, "dry_run", False)
    path = manifest_path(args.manifest)
    scope = args.scope or ("user" if args.global_scope else "project")
    if args.global_scope and args.scope == "project":
        parser.error("--global conflicts with --scope project")
    options = BackendOptions(agent=args.agent, scope=scope)

    if command == "path":
        print(path)
        return 0

    try:
        manifest = load_manifest(path)
    except Exception as error:
        print(f"skeel: {error}", file=sys.stderr)
        return 2

    try:
        if command == "plan":
            return command_plan(manifest, options)
        if command == "diff":
            return command_diff(manifest, options)
        if command in {"apply", "sync"}:
            return command_apply(manifest, options, dry_run=dry_run)
        if command == "update":
            return command_update(manifest, options, dry_run=dry_run)
    except Exception as error:
        print(f"skeel: {error}", file=sys.stderr)
        return 2

    parser.error(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
