"""Bootstrap the portable engineering gate into an existing source repository."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shlex

from .guard import (PY_MODULE, TS_MODULE, PACKAGE, VERSION, _canonical_sha256, _source_path,
                    load_policy, main as guard_main, relaxation_changes, validate_policy)


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
        with:
          fetch-depth: 0
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
        env:
          GUARD_CI_BASE: ${{ github.event.pull_request.base.sha || github.event.before }}
        run: |
          BASE_ARGS=()
          if [ -n "$GUARD_CI_BASE" ]; then BASE_ARGS+=(--ci-base "$GUARD_CI_BASE"); fi
          python .agent-engineering/guard.py check "${BASE_ARGS[@]}"
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

def relax(args: argparse.Namespace) -> int:
    """Record a reasoned loosening of a strict policy; the only supported write path."""
    root = args.repo.expanduser().resolve()
    policy = load_policy(root)
    if not policy.get("strict"):
        raise ValueError('policy "strict" is not enabled; set it directly (tightening never needs relax)')
    reason = args.reason.strip()
    if not reason:
        raise ValueError("--reason must be a non-empty explanation")
    new = json.loads(json.dumps(policy))

    def drop_pair(field: str, pair: str, label: str) -> None:
        parts = pair.split(":")
        if len(parts) != 2 or [parts[0], parts[1]] not in (policy.get(field) or []):
            raise ValueError(f"--{label} {pair!r}: edge not present in policy {field}")
        new[field].remove([parts[0], parts[1]])

    def remove_module(module: str, unmanage: bool) -> None:
        flag = "--unmanage" if unmanage else "--remove-module"
        if unmanage and module in (new.get("unmanaged_modules") or []):
            raise ValueError(f"{flag} {module!r}: module is already unmanaged")
        if unmanage and "modules" not in new:
            raise ValueError(f"{flag} {module!r}: policy has no modules allowlist; nothing to unmanage")
        if not unmanage and module not in (new.get("modules") or []):
            raise ValueError(f"{flag} {module!r}: module is not declared in modules")
        if "modules" in new:
            new["modules"] = [m for m in new["modules"] if m != module]
        if "allowed_dependencies" in new:
            new["allowed_dependencies"] = [edge for edge in new["allowed_dependencies"] if module not in edge]
        if not unmanage:
            new["forbidden"] = [pair for pair in new["forbidden"] if module not in pair]
        else:
            new.setdefault("unmanaged_modules", []).append(module)

    for pair in args.remove_forbidden:
        drop_pair("forbidden", pair, "forbidden")
    for pair in args.remove_allowed:
        drop_pair("allowed_dependencies", pair, "allowed")
    for module in args.unmanage:
        remove_module(module, unmanage=True)
    for module in args.remove_module:
        remove_module(module, unmanage=False)
    if args.coverage_off:
        if new.get("module_coverage") == "off":
            raise ValueError("--coverage-off: module coverage is already off")
        new["module_coverage"] = "off"
    if args.no_cycles:
        if not new.get("check_cycles", new["language"] == "typescript"):
            raise ValueError("--no-cycles: cycle checking is already disabled")
        new["check_cycles"] = False
    for index in args.remove_test:
        if not 1 <= index <= len(new["tests"]):
            raise ValueError(f"--remove-test {index}: out of range (1-{len(new['tests'])});"
                             " indexes shift after each removal")
        new["tests"].pop(index - 1)
    if args.strict_off:
        new["strict"] = False
    validate_policy(new)
    actual = relaxation_changes(policy, new)
    if not actual:
        raise ValueError("no relaxation requested; tighten the policy by editing policy.json directly")
    entries = new.get("relaxations") or []
    entry = {
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": reason,
        "changes": actual,
        "prev_entry_sha256": _canonical_sha256(entries[-1]) if entries else "0" * 64,
    }
    new["relaxations"] = entries + [entry]
    (root / ".agent-engineering" / "policy.json").write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    print("RELAXED:", "; ".join(actual))
    print("REASON:", reason)
    return 0

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
    relax_parser = commands.add_parser("relax", help="record a reasoned policy loosening (strict mode)")
    relax_parser.add_argument("repo", type=Path)
    relax_parser.add_argument("--reason", required=True, help="why this loosening is justified")
    relax_parser.add_argument("--remove-forbidden", action="append", default=[], metavar="SRC:DST")
    relax_parser.add_argument("--remove-allowed", action="append", default=[], metavar="SRC:DST")
    relax_parser.add_argument("--remove-module", action="append", default=[], metavar="MODULE",
                              help="remove a declared module; drops its forbidden pairs and allowed edges")
    relax_parser.add_argument("--unmanage", action="append", default=[], metavar="MODULE")
    relax_parser.add_argument("--coverage-off", action="store_true")
    relax_parser.add_argument("--no-cycles", action="store_true")
    relax_parser.add_argument("--remove-test", action="append", default=[], type=int, metavar="N",
                              help="1-based tests entry to remove; indexes shift after each removal")
    relax_parser.add_argument("--strict-off", action="store_true")
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
        if args.command == "relax":
            return relax(args)
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
