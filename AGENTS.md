# Coding Agent Instructions

This repository maintains reusable architecture checks for other projects. Make the smallest change that preserves a single project-owned policy file.

- Read `README.md`, `engineering_kit/guard.py`, and relevant tests before modifying behavior.
- Do not duplicate policy logic in the CLI, workflow templates, or a second config.
- Do not add a new abstraction for one caller. Keep functions focused and most below 50 lines.
- Keep the per-project guard Python-standard-library only; external import analysis belongs to Import Linter or dependency-cruiser.
- Do not silently overwrite existing project files or remove a user-created AGENTS.md.
- Guard failures must return a nonzero exit code; never treat missing tools, missing modules, or failing tests as a success.
- Preserve compatibility with previously initialized project policies unless explicitly documenting migration.
- Run `python -m unittest discover -s tests -p 'test_kit.py' -v` and real adapter tests where installed.
- Never weaken a check or edit the tests merely to obtain green CI; add a regression test for each bug.
- Do not claim GitHub Actions, a release, or a third-party adapter passed without an observed receipt.
