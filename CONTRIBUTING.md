# Contributing

Thanks for contributing! We want a **small, predictable** tool instead of a large framework.

## Principles

- Avoid reimplementing parser/dependency discovery logic: reuse existing language tools.
- Put universal checks in `engineering_kit/guard.py`; keep project-specific policy in `policy.json`.
- Keep the generated runner free of third-party Python imports. CI must work without an AEK PyPI package.
- Do not make an agent or server mandatory for quality gates.
- Do not silently change or overwrite files in the target repository.
- Add tests for every guard behavior and update both English and Chinese docs when user-facing behavior changes.

## Changes

1. Open an issue describing the problem or a focused feature.
2. Submit a small PR with a test. Run `python -m unittest discover -s tests -v`.
3. Include an actual sample-project test when changing Python/TypeScript checker invocation.
4. Document schema updates and preserve compatibility or provide a migration step.

Generated CI and project policy are security-sensitive: policy changes should be reviewed carefully. Treat strings in policy files as repository-controlled, not as trusted network input. Runner uses argument arrays rather than a shell.

## Releasing

Maintainers choose a release tag, update version in `pyproject.toml`, `engineering_kit/__init__.py`, and `engineering_kit/guard.py`, run checks, build the package, and only then publish to a chosen registry. Public maintainers, governance and ownership should be decided by the repository owner.

MIT contributions should be your own or appropriately licensed. By contributing you agree that your work is distributed under the repository MIT license.

## Adapter verification before a release

Run the unit suite, then the real adapter integration suite with `AEGKIT_REQUIRE_ADAPTERS=1` after installing the optional tooling. The integration tests deliberately introduce forbidden imports and must fail those checks. A mocked checker alone is not a release acceptance test. Make GitHub's `real-adapters` check required on PRs.

If you change a policy schema or add a language adapter, update `tests/integration` before changing the release version.
