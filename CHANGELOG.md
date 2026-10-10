## 0.3.3 — Publication handoff

- Added reviewed, opt-in GitHub public repository publishing helper (dry-run by default).
- Added reusable GitHub Ruleset generator using exact CI job contexts, with no bypass actors and no silent overwrites.
- Added public release instructions, private-repository plan caveats, and regression tests for publication configuration.
- No changes to the project architecture guard's runtime behavior.

# Changelog

## 0.4.0 (unreleased candidate)
- Optional strict mode (`"strict": true`): policy loosening requires a reasoned, tamper-evident `relaxations` entry chain; CI (`--ci-base`) fails on naked relaxations and on policy edits mixed with code changes.
- New `aegkit relax` command records every loosening with a mandatory reason.
- Generated CI passes the base ref so strict isolation is enforced on pull requests and pushes.
- Backward compatible: policies without `strict`/`relaxations` behave exactly as 0.3.3.

## 0.3.3 (unreleased candidate)
- Real Import Linter 2.15 and dependency-cruiser 17 regressions verified in isolated environments: clean, violating, repaired; TypeScript type-only imports were rejected.
- Fail closed on command timeouts (default 15 minutes; optional per-project `command_timeout_seconds` between 1 and 3600); timed out checks return exit code 124.
- TypeScript doctor now verifies that dependency-cruiser actually executes, not merely that `npx` is installed.
- Public GitHub release and end-to-end hosted CI verification remain pending.

## 0.3.1 (unreleased candidate)
- New projects opt into Python top-level sibling cycle detection; previously initialized policies retain legacy behavior unless `check_cycles` is enabled.
- TypeScript dependency inspection now includes type-only and unused imports that are otherwise discarded during compilation.
- Added integration fixtures for cycle violations and type-only dependency violations.

## 0.3.0 (unreleased candidate)
- Optional strict allowlist for declared architecture modules.
- Top-level module coverage checks for strict mode; explicit unmanaged exceptions.
- CI black-box adapter regression tests (clean / violated / repaired) with required dependency checks.
- Fail-closed JSON reporting even on invalid/missing policy.
- TypeScript unresolved imports treated as violations.
- Pinned local policy fingerprint in successful JSON reports.
- Backward-compatible with v0.2 policy schema version 1.

## 0.2.0 — 2026-10-08
- Added pip-installable `aegkit` command and portable, standalone per-project guard.
- Introduced single-source `.agent-engineering/policy.json` and generated native checker configs at runtime.
- Combined architecture boundaries and project-supplied behavior tests into one CI acceptance check.
- Validated declared module existence to prevent vacuous successes.
- Added CI, reproducible tests, MIT license, contribution guide, and bilingual documentation.

## 0.1.0 — 2026-10-08
- Initial scaffolder with per-project `AGENTS.md`, `CLAUDE.md`, and CI template.
