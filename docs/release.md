# Release checklist

AEK has not been published to a public GitHub repository or PyPI.

1. Review license, README, SECURITY.md, and dependency versions.
2. Run the unit and *real-adapters* suites in CI, requiring both checks.
3. Verify a clean integration in a Python and a TypeScript project with actual modules.
4. Build wheel and sdist, inspect archive contents (no caches, credentials, or build debris).
5. Add branch protection for `test` and `real-adapters` checks and review on policy/CI changes.
6. Use `docs/github-publication.md` and the opt-in publication helper to create a new public repository; check the result on GitHub before making a release tag.
7. If publishing to PyPI, configure a restricted Trusted Publisher and a separate
   `release.yml` with `id-token: write` and a protected GitHub environment.
8. Only after publication, update installation links, badges and release status.

Never claim a release is published from a local wheel or source ZIP alone.

The helper commands are intentionally dry-run by default. `--apply` changes GitHub state and requires authenticated GitHub CLI and sufficient privileges.
