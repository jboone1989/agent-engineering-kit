"""Prepare or publish a clean AEK Git checkout to a NEW public GitHub repo.

No network or side effects unless --apply is explicitly supplied. Requires gh
CLI authenticated as the target personal account; never asks for a token.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

DESCRIPTION = "Portable architecture and behavior-test gates for AI coding agents"


def command(owner: str, name: str, directory: Path) -> list[str]:
    return ["gh", "repo", "create", f"{owner}/{name}", "--public",
            "--description", DESCRIPTION, "--source", str(directory),
            "--remote", "origin", "--push"]


def check_checkout(directory: Path) -> None:
    if not (directory / "LICENSE").is_file() or not (directory / "AGENTS.md").is_file():
        raise ValueError("Missing open-source LICENSE or AGENTS.md")
    result = subprocess.run(["git", "-C", str(directory), "status", "--porcelain"],
                            check=True, capture_output=True, text=True)
    if result.stdout.strip():
        raise ValueError("Checkout has uncommitted or untracked files; publish a reviewed commit")
    branch = subprocess.run(["git", "-C", str(directory), "branch", "--show-current"],
                            check=True, capture_output=True, text=True).stdout.strip()
    if branch != "main":
        raise ValueError(f"Expected reviewed main branch, got {branch!r}")


def publish(owner: str, name: str, directory: Path, *, apply: bool) -> None:
    if not owner or not name or any(c.isspace() for c in owner + name):
        raise ValueError("Provide a nonblank owner and repository name")
    check_checkout(directory)
    args = command(owner, name, directory)
    print("Planned public repository:", f"{owner}/{name}")
    print("Command:", " ".join(args))
    if not apply:
        print("DRY RUN only. Use --apply after inspecting source and GitHub account.")
        return
    subprocess.run(["gh", "auth", "status"], check=True)
    login = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                           check=True, capture_output=True, text=True).stdout.strip()
    if login.casefold() != owner.casefold():
        raise ValueError(f"GitHub login {login!r} differs from intended personal owner {owner!r}")
    exists = subprocess.run(["gh", "repo", "view", f"{owner}/{name}"],
                            capture_output=True, text=True)
    if exists.returncode == 0:
        raise ValueError("Remote repository already exists; refusing to overwrite or push")
    subprocess.run(args, check=True)
    details = subprocess.run(["gh", "repo", "view", f"{owner}/{name}",
                              "--json", "url,visibility"],
                             check=True, capture_output=True, text=True)
    import json
    published = json.loads(details.stdout)
    if published.get("visibility", "").upper() != "PUBLIC":
        raise ValueError("Repository exists but is not PUBLIC: " + str(published))
    print("PUBLIC REPOSITORY CONFIRMED:", published["url"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--name", default="agent-engineering-kit")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true", help="Create the PUBLIC repository")
    args = parser.parse_args(argv)
    try:
        publish(args.owner, args.name, args.source.resolve(), apply=args.apply)
        return 0
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"PUBLICATION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
