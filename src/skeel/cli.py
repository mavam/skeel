from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator

from . import __version__
from .backends import (
    InstallStep,
    Runner,
    ensure_claude_symlink,
    get_backend,
    installed_skill_names,
    manual_install_steps,
    quote_command,
    symlink_step,
)
from .manifest import Manifest, load_manifest, manifest_path


def use_color() -> bool:
    return os.environ.get("NO_COLOR") is None


def red(text: str) -> str:
    return f"\033[31m{text}\033[0m" if use_color() else text


def green(text: str) -> str:
    return f"\033[32m{text}\033[0m" if use_color() else text


def diff_sets(manifest: Manifest) -> tuple[list[str], list[str]]:
    desired = manifest.desired_skill_names
    installed = installed_skill_names(manifest.shared_dir)
    return sorted(desired - installed), sorted(installed - desired)


def print_diff(manifest: Manifest, *, warning: bool = False) -> bool:
    missing, extra = diff_sets(manifest)
    if not missing and not extra:
        return False
    if warning:
        print(f"⚠️  Installed skills differ from {manifest.path}:", file=sys.stderr)
    for name in missing:
        print(red(f"- {name}"), file=sys.stderr)
    for name in extra:
        print(green(f"+ {name}"), file=sys.stderr)
    return True


def iter_install_plan(manifest: Manifest) -> Iterator[InstallStep]:
    for source in manifest.sources:
        if source.install:
            yield from manual_install_steps(source)
            continue
        backend = get_backend(source.backend)
        for skill in source.skills:
            yield from backend.install_steps(manifest, source, skill)
            if step := symlink_step(manifest, skill):
                yield step


def command_plan(manifest: Manifest) -> int:
    for step in iter_install_plan(manifest):
        print(quote_command(step.command))
    return 0


def command_diff(manifest: Manifest) -> int:
    return 1 if print_diff(manifest) else 0


def command_apply(manifest: Manifest, *, dry_run: bool = False) -> int:
    print_diff(manifest, warning=True)
    runner = Runner(dry_run=dry_run)
    for source in manifest.sources:
        if source.install:
            for step in manual_install_steps(source):
                print(f"📦 Installing {step.label}…")
                runner.run(step)
            continue
        backend = get_backend(source.backend)
        for skill in source.skills:
            for step in backend.install_steps(manifest, source, skill):
                print(f"📦 Installing {step.label} → {manifest.shared_dir}…")
                runner.run(step)
            if not dry_run:
                ensure_claude_symlink(manifest, skill)
            else:
                link_step = symlink_step(manifest, skill)
                if link_step:
                    print(quote_command(link_step.command))
    print("✅ Skills applied.")
    return 0


def command_update(manifest: Manifest, *, dry_run: bool = False) -> int:
    print_diff(manifest, warning=True)
    runner = Runner(dry_run=dry_run)
    backends = {source.backend for source in manifest.sources if not source.install}
    print("🧠 Updating skills…")
    for backend_name in sorted(backends):
        backend = get_backend(backend_name)
        for step in backend.update_steps(manifest):
            runner.run(step, keep_going=True)
    print("✅ Skills updated.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Declarative agent skill manager")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", "-c", help="Manifest path (default: ~/.agents/.skill.yaml)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without applying changes",
    )
    subparsers = parser.add_subparsers(dest="command")
    for name in ["path", "plan", "diff", "apply", "sync", "update"]:
        subparsers.add_parser(name)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "plan"
    path = manifest_path(args.config)

    if command == "path":
        print(path)
        return 0

    try:
        manifest = load_manifest(path)
    except Exception as error:
        print(f"skeel: {error}", file=sys.stderr)
        return 2

    if command == "plan":
        return command_plan(manifest)
    if command == "diff":
        return command_diff(manifest)
    if command in {"apply", "sync"}:
        return command_apply(manifest, dry_run=args.dry_run)
    if command == "update":
        return command_update(manifest, dry_run=args.dry_run)

    parser.error(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
