"""Bootstrap the portable engineering gate into an existing source repository."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex

from .guard import PY_MODULE, TS_MODULE, PACKAGE, VERSION, _source_path, load_policy, main as guard_main, validate_policy


def parse_rules(items: list[str], language: str, required: bool = True) -> list[list[str]]:
    result = []
    module_pattern = PY_MODULE if language == "python" else TS_MODULE
    for item in items:
        pair = item.split(":")
        if len(pair) != 2 or any(not module_pattern.fullmatch(x) for x in pair) or pair[0] == pair[1]:
            raise ValueError(f"invalid --forbid {item!r}: expected distinct module:module")
        if pair not in result:
            result.append(pair)
    if required and not result:
        raise ValueError("at least one dependency edge is required")
    return result


def write_new(path: Path, content: str, skipped: list[str]) -> None:
    if path.exists():
        skipped.append(str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print("CREATED:", path)


def agents_text() -> str:
    return """# Engineering contract for coding agents

Before editing: read ARCHITECTURE.md and .agent-engineering/policy.json; identify the owning module and impacted public contracts.

While editing:
- Change the owning module first; do not add unrelated refactors.
- Do not add forbidden or circular dependencies, shared mutable global state, or redundant fallback paths.
- Separate coordination, business logic and infrastructure. Prefer a direct public interface for synchronous work; use events when independence is useful.
- Keep most functions under 50 lines; review functions above 100 lines. Never split solely to satisfy line counts.
- Do not weaken .agent-engineering/policy.json, the guard, or CI to make a feature pass.

Before reporting completion:
- Run `python .agent-engineering/guard.py check` (architecture AND behavior tests).
- Explain the owner module, changed public interfaces, tests actually run, outstanding failures, and any new coupling.
- Passing behavior tests alone is not sufficient. For a necessary policy change, seek a separate human review.
"""


def architecture_text(name: str, policy: dict) -> str:
    from .guard import forbidden_pairs
    rows = "\n".join(f"| `{a}` | `{b}` |" for a, b in forbidden_pairs(policy))
    return (f"# {name}: architecture contract\n\n"
            "Document module ownership and the reason for each boundary here.\n"
            "Each feature must have one owning module; other modules may use public contracts.\n\n"
            "## Explicitly forbidden dependencies\n\n"
            "| From | Must not depend on |\n| --- | --- |\n" + rows + "\n\n"
            "## Ownership (fill in with actual project modules)\n\n"
            "| Module | Owns | Public API |\n| --- | --- | --- |\n| TODO | TODO | TODO |\n\n"
            "The machine-readable source of truth is `.agent-engineering/policy.json`.\n"
            "Changing boundaries requires a separate review; don't silently relax them.\n")


def workflow(language: str) -> str:
    head = """name: engineering-guard
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
"""
    if language == "python":
        steps = """      - name: Install project and architecture checker
        run: |
          python -m pip install 'import-linter>=2,<3'
          # If your project needs installation to run its tests, add its usual dependency setup here.
"""
    else:
        steps = """      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
      - run: npm ci
      # The project must contain dependency-cruiser in devDependencies.
"""
    return head + steps + """      - name: Enforce module boundaries and run behavior tests
        run: python .agent-engineering/guard.py check
"""



def managed_outputs(policy: dict) -> dict[str, str]:
    from . import guard
    return {
        ".agent-engineering/guard.py": Path(guard.__file__).read_text(encoding="utf-8"),
        ".github/workflows/engineering-guard.yml": workflow(policy["language"]),
    }


def fingerprint(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def sync(root: Path) -> int:
    """Update only unmodified kit-owned files; leave the project's policy untouched."""
    policy = load_policy(root)
    manifest = root / ".agent-engineering/managed.json"
    try:
        state = json.loads(manifest.read_text(encoding="utf-8"))
        known = state["files"]
        if not isinstance(known, dict):
            raise ValueError("files must be a map")
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {manifest} missing or invalid; refuse untracked overwrite: {exc}")
        return 2
    failed = []
    updated = []
    for relative, body in managed_outputs(policy).items():
        path = root / relative
        old_hash = known.get(relative)
        if not isinstance(old_hash, str) or not path.is_file() or fingerprint(path.read_text(encoding="utf-8")) != old_hash:
            failed.append(relative)
            continue
        if fingerprint(body) != old_hash:
            path.write_text(body, encoding="utf-8")
            updated.append(relative)
            known[relative] = fingerprint(body)
    if failed:
        print("NOT UPDATED (untracked or locally edited; merge manually):", ", ".join(failed))
        # Do not erase the tracking state for files that did update safely.
    state["kit_version"] = VERSION
    manifest.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print("SYNC COMPLETE; updated:", ", ".join(updated) if updated else "none")
    return 2 if failed else 0

def init(args: argparse.Namespace) -> int:
    root = args.repo.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("existing project directory required; refusing to create one")
    if args.language == "python" and not (args.package and PACKAGE.fullmatch(args.package)):
        raise ValueError("--package required (valid dotted Python package)")
    if args.language == "typescript":
        _source_path(args.source)
    tests = [shlex.split(s) for s in args.test]
    if any(not t for t in tests):
        raise ValueError("--test requires a non-empty command")
    policy = {
        "schema_version": 1,
        "language": args.language,
        "package": args.package if args.language == "python" else None,
        "source": args.source if args.language == "typescript" else None,
        "forbidden": parse_rules(args.forbid, args.language, required=False),
        "check_cycles": True,
        "tests": tests,
    }
    if args.module or args.allow:
        policy["modules"] = args.module
        policy["allowed_dependencies"] = parse_rules(args.allow, args.language, required=False)
    validate_policy(policy)
    skipped = []
    files = {
        "AGENTS.md": agents_text(),
        "CLAUDE.md": "@AGENTS.md\n",
        "ARCHITECTURE.md": architecture_text(root.name, policy),
        ".agent-engineering/policy.json": json.dumps(policy, indent=2) + "\n",
        **managed_outputs(policy),
    }
    for rel, body in files.items():
        write_new(root / rel, body, skipped)
    managed = managed_outputs(policy)
    tracked = {rel: fingerprint(body) for rel, body in managed.items()
               if (root / rel).is_file() and str(root / rel) not in skipped}
    write_new(root / ".agent-engineering/managed.json",
              json.dumps({"kit_version": VERSION, "files": tracked}, indent=2) + "\n", skipped)
    if not tests:
        print("WARNING: no behavior tests configured. Set tests in policy.json before check/CI.")
    if skipped:
        print("NOT OVERWRITTEN (manual merge required):")
        for item in skipped:
            print(" -", item)
        return 2
    print("NEXT: review module paths; install adapter dependencies; add existing test setup to CI; run guard.py check.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Engineering Kit")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("init", help="install the portable guard (no overwrite)")
    setup.add_argument("repo", type=Path)
    setup.add_argument("--language", choices=("python", "typescript"), required=True)
    setup.add_argument("--package", help="Python import root, e.g. ferro")
    setup.add_argument("--source", default="src", help="TypeScript source folder, default src")
    setup.add_argument("--forbid", action="append", default=[], help="source:target (repeatable)")
    setup.add_argument("--module", action="append", default=[], help="allowlist module (repeatable)")
    setup.add_argument("--allow", action="append", default=[], help="permitted source:target (repeatable)")
    setup.add_argument("--test", action="append", default=[], help='test argv e.g. "python -m pytest -q" (repeatable)')
    sync_parser = commands.add_parser("sync", help="safely update kit-owned runner and CI, not project policy")
    sync_parser.add_argument("repo", type=Path)
    for command in ("check", "doctor", "render-config"):
        sub = commands.add_parser(command, help=f"run project {command}")
        sub.add_argument("--root", type=Path, default=Path.cwd())
        if command == "check":
            sub.add_argument("--arch-only", action="store_true")
            sub.add_argument("--json-report", type=Path)
            sub.add_argument("--ci-base")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return init(args)
        if args.command == "sync":
            return sync(args.repo.expanduser().resolve())
    except ValueError as exc:
        parser.error(str(exc))
    guard_args = [args.command, "--root", str(args.root)]
    if getattr(args, "arch_only", False):
        guard_args.append("--arch-only")
    if getattr(args, "json_report", None):
        guard_args += ["--json-report", str(args.json_report)]
    if getattr(args, "ci_base", None):
        guard_args += ["--ci-base", args.ci_base]
    return guard_main(guard_args)
