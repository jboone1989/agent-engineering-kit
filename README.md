# Agent Engineering Kit (AEK)

[![CI](https://img.shields.io/badge/CI-local%20and%20GitHub%20Actions-blue)](./.github/workflows/tests.yml)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

**Short instructions for coding agents. Enforceable architecture boundaries and behavior tests for every change.**

Most agent rules live only in prompts. AEK installs a **small, auditable guard** into each project so CI can enforce the same architectural boundaries regardless of which coding model is used.

**Status:** `0.3.3` alpha, open-source-ready source distribution. Not published to PyPI or a public GitHub repository yet. Python and TypeScript are implemented; Java is documentation-only. The tool does **not** automatically discover your system's correct architecture.

## GitHub publication and enforcement

For verified, opt-in public repository creation and required-status-check rulesets, see [GitHub publication](docs/github-publication.md). Both helpers default to a no-write preview and require an authenticated GitHub CLI plus an explicit `--apply` to change GitHub state.

## Quick start

Install from this source tree (no external Python runtime dependencies):

```bash
python -m pip install -e .
```

Add to an **existing** Python repository. Replace the module names with actual modules:

```bash
aegkit init /path/to/your-project \
  --language python --package mypackage \
  --forbid learning:publishing \
  --test "python -m unittest discover -s tests"

cd /path/to/your-project
python -m pip install 'import-linter>=2,<3'
python .agent-engineering/guard.py doctor
python .agent-engineering/guard.py check
```

For an existing TypeScript project:

```bash
aegkit init /path/to/ts-project \
  --language typescript --source src \
  --forbid learning:publishing \
  --test "npm test -- --runInBand"

cd /path/to/ts-project
npm install -D dependency-cruiser
python .agent-engineering/guard.py check
```

The TypeScript test command is only an **example**; use your actual test runner and flags. The CI uses `npm ci`, so commit `package-lock.json` after adding dependency-cruiser. The generated Python CI installs Import Linter but may also need your project's existing test dependencies. Add the normal installation steps to the workflow. CI is not considered ready until a real PR exercises it.

### Files installed in the target project

```text
AGENTS.md                            # portable rules for coding agents
CLAUDE.md                           # references AGENTS.md for Claude Code
ARCHITECTURE.md                     # boundary rationales and ownership
.agent-engineering/
  policy.json                       # ONLY source of truth for boundaries + tests
  guard.py                          # standalone Python-stdlib runner; CI executes this
  managed.json                      # hashes for safe future tool upgrades
.github/workflows/
  engineering-guard.yml             # PR and main-branch quality gate
```

`init` **never overwrites** existing files. An existing file is printed for manual merging and the command returns a non-zero status. Do not assume the policy is installed if you see an `NOT OVERWRITTEN` warning.

## Core design

**Project-specific policy, shared portable engine.** AEK generates the Import Linter / dependency-cruiser configuration **in memory at runtime from one `policy.json`**. There is no second copy of architectural policy in the CI YAML. The generated CI invokes the vendored guard, so the target project does not depend on an as-yet-unpublished AEK PyPI package.

Example project configuration (legacy denylist mode):

```json
{
  "schema_version": 1,
  "language": "python",
  "package": "mypackage",
  "source": null,
  "forbidden": [["learning", "publishing"], ["publishing", "memory"]],
  "tests": [["python", "-m", "unittest", "discover", "-s", "tests"]]
}
```

For stronger enforcement, use an **allowlist** and enumerate the modules you want governed:

```json
{
  "schema_version": 1,
  "language": "python",
  "package": "mypackage",
  "source": null,
  "modules": ["learning", "memory", "publishing", "contracts"],
  "allowed_dependencies": [
    ["learning", "contracts"],
    ["memory", "contracts"],
    ["publishing", "contracts"]
  ],
  "forbidden": [],
  "check_cycles": true,
  "module_coverage": "top_level",
  "tests": [["python", "-m", "pytest", "-q"]]
}
```

Or initialize allowlist mode with repeated `--module` and `--allow source:target` flags.
Every undeclared edge **between these declared modules** is forbidden. With `module_coverage: "top_level"` (the default in allowlist mode), newly added top-level source modules cause a failure until you add them to `modules`, or explicitly name documented exceptions in `unmanaged_modules`. Deep nested boundaries and shared databases still require deliberate design and tests; this is not a total semantic coupling proof. `module_coverage: "off"` is available for staged migration, but weakens enforcement. The legacy `forbidden` entries remain supported for gradual adoption. Python's forbidden contracts check transitive imports; TypeScript's rules inspect direct resolved imports and cycles. New project initializations set `check_cycles: true`; existing policies without this key preserve the previous Python behavior until explicitly upgraded.

Each `forbidden` pair means **the module on the left must not depend on the module on the right**. Rules apply to existing declared modules, not arbitrary source labels; if a named module does not exist, `check` fails rather than claiming success. Import Linter also inspects indirect imports; dependency-cruiser checks declared edges and (by default) circular imports on resolved source paths, including type-only imports (`tsPreCompilationDeps`). With `check_cycles: true`, Python uses Import Linter's `acyclic_siblings` contract at depth 0 to detect cycles between top-level children of the package (not every nested cycle). Setting `check_cycles: false` disables the explicit cycle contract (not recommended); legacy TypeScript policies without this key still check cycles, whereas legacy Python policies do not. TypeScript path aliases require valid resolution configuration (usually `tsconfig.json`).

### Upgrading the shared kit without overwriting project-specific policy

After installing a newer AEK version, run:

```bash
aegkit sync /path/to/your-project
```

`sync` updates only kit-owned runner/CI files whose content still matches the last generated version (`managed.json` hash). It **never edits** `policy.json`, `AGENTS.md`, or `ARCHITECTURE.md`. If an integrator changed the runner or workflow, AEK refuses the overwrite and asks for a manual merge. For a v0.1 project, adopt the new policy and guard first; its old scaffolder did not create a managed manifest.

### Policy erosion protection (strict mode)

Setting `"strict": true` in `policy.json` makes silent loosening impossible to merge:

- **Isolated policy PRs.** With a base ref (the generated CI passes one), a `policy.json` change may only touch `.agent-engineering/**`, `engineering-guard.yml`, or `ARCHITECTURE.md`. Land the policy first, then use the new freedom in a separate PR.
- **No naked relaxations.** Removing a forbidden pair, an allowed edge, a declared module, module coverage, cycle checks, tests, or strict itself requires a `relaxations` entry — a dated, reasoned record chained to the previous entry by SHA-256. Deleting or editing history breaks the chain and fails every check.
- **`aegkit relax`.** The only supported way to loosen a strict policy; it refuses empty reasons and refuses anything that is not an actual loosening:

```bash
aegkit relax /path/to/your-project --reason "memory layer retired" --remove-forbidden publishing:memory
```

Strict mode is opt-in; policies without these fields behave exactly as before. Human review of policy PRs remains the final gate — the chain makes loosening loud and attributable, not impossible.

## Coding-agent cycle

1. Identify the owning module and public API before coding.
2. Implement the smallest change within the allowed architecture.
3. Run the existing behavior tests and the architecture checker via one command.
4. Report any new dependencies and failures. **Never weaken the policy to get green.**
5. Require a human review for policy-file changes; make the GitHub PR check mandatory in repository rulesets.

**Guard execution:**

```bash
python .agent-engineering/guard.py doctor
python .agent-engineering/guard.py check
python .agent-engineering/guard.py check --json-report /tmp/aegkit-report.json
python .agent-engineering/guard.py check --arch-only  # diagnostic; NOT full acceptance
python .agent-engineering/guard.py render-config     # inspect generated native config
```

Commands time out after 900 seconds by default; override with `"command_timeout_seconds": 1200` in `policy.json` (valid range: 1–3600). A timed-out step fails the check rather than hanging indefinitely. The TypeScript `doctor` command verifies that dependency-cruiser itself runs, not just `npx`.

By default, `check` **fails** if behavior tests are not configured. `--arch-only` exists for adoption/diagnosis, not for merging production changes. The guard prints concise pass/fail results and retains no logs or telemetry unless you explicitly request a JSON result.

## What it cannot enforce automatically

- Semantic module boundaries, ownership or good abstractions: humans/agents must specify them.
- All forms of coupling (shared database schemas, mutable runtime state, events or APIs).
- Validity or coverage of a project's test suite.
- Branch protection: you must configure a GitHub ruleset requiring `quality-gate` and review on policy changes.
- A policy can still be weakened in the same PR unless a reviewer / CODEOWNERS / ruleset protects it.
- Erosion that humans approve: the relaxations chain records and exposes loosening, but a reviewed `aegkit relax` is by design allowed. The chain stops silent erosion, not decided erosion.

**Important:** a build passing the generated guard is necessary, not sufficient, for maintainable software. AEK intentionally does not introduce another agent, memory system, or policy server.

## Support matrix

| Environment | Bootstrap | Enforcement | Notes |
| --- | --- | --- | --- |
| Python | Yes | Import Linter | forbidden module paths and transitive imports |
| TypeScript / JavaScript | Yes | dependency-cruiser | module dependencies, circular imports |
| Java / JVM | Example | ArchUnit by project | see [JVM adapter guide](docs/java.md) |
| Go / Rust | No | Bring your own | possible future adapters |
| Codex and AGENTS.md readers | Yes | Repository instructions | rules are guidance; CI is enforcement |
| Claude Code | Yes | CLAUDE.md reference | same repository contract |

## Integration test contract

The project's CI includes `real-adapters`, which installs Import Linter and dependency-cruiser and executes black-box regressions: pass → deliberately introduced architectural violation → pass again. These now include Python sibling cycles and TypeScript type-only imports. The ordinary unit suite mocks the external executables and does not prove real adapter behavior. **Do not publish unless the real-adapters CI job passes.**

```bash
AEGKIT_REQUIRE_ADAPTERS=1 python -m unittest discover -s tests/integration -v
```

`AEGKIT_REQUIRE_ADAPTERS=1` prevents false success due to missing third-party tools. Local integration tests skip when adapters are unavailable and the environment flag is not set.

## Contributing and release

See [adoption guide](docs/adoption-guide.md), [release checklist](docs/release.md), [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), [docs/中文使用指南.md](docs/中文使用指南.md), and [CHANGELOG.md](CHANGELOG.md).

Run the unit tests:

```bash
python -m unittest discover -s tests -p "test_kit.py" -v
```

Releases should run tests, build a wheel + source distribution, check package metadata, tag the version and verify integration on a clean Python + TypeScript sample project **before** publishing. No repository URL or package registry listing is claimed until published.

License: [MIT](LICENSE).
