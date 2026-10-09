"""Generate or apply a GitHub main-branch Ruleset for known passing CI job names.

No GitHub API calls without --apply. Does NOT weaken or overwrite other rulesets.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys



def payload(name: str, branch: str, checks: tuple[str, ...]) -> dict:
    if not checks or len(checks) != len(set(checks)) or any(not x.strip() for x in checks):
        raise ValueError("Provide unique nonblank names of actual GitHub Actions jobs")
    return {
        "name": name,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": [f"refs/heads/{branch}"], "exclude": []}},
        "rules": [{
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "do_not_enforce_on_create": True,
                "required_status_checks": [{"context": check} for check in checks],
            },
        }],
    }


def apply_ruleset(repo: str, rules: dict) -> None:
    subprocess.run(["gh", "auth", "status"], check=True)
    existing = subprocess.run(["gh", "api", f"repos/{repo}/rulesets", "--jq", ".[].name"],
                              check=True, capture_output=True, text=True)
    if rules["name"] in existing.stdout.splitlines():
        raise ValueError("Named ruleset already exists; inspect it instead of creating a duplicate")
    subprocess.run(["gh", "api", "--method", "POST", f"repos/{repo}/rulesets",
                    "--input", "-"], input=json.dumps(rules), text=True, check=True)
    print("Ruleset created; verify enforcement in GitHub Settings > Rules > Rulesets")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub owner/repository")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--name", default="Agent architecture and regression gates")
    parser.add_argument("--checks", nargs="+", required=True,
                        help="Exact GitHub Actions JOB names from a successful workflow run")
    parser.add_argument("--apply", action="store_true", help="Create ACTIVE ruleset")
    args = parser.parse_args(argv)
    if len(args.repo.split("/")) != 2 or not all(args.repo.split("/")):
        parser.error("--repo must have owner/repository format")
    try:
        rules = payload(args.name, args.branch, tuple(args.checks))
        print(json.dumps(rules, indent=2, ensure_ascii=False))
        if args.apply:
            apply_ruleset(args.repo, rules)
        else:
            print("DRY RUN only. Use --apply after checking plan support, admin permissions and job names.")
        return 0
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"RULESET NOT INSTALLED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
