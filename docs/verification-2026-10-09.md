# Real-adapter verification: 2026-10-09

This note separates **observed results** from release blockers. The tests were performed without changing the `agent-runtime` working tree or restarting production services.

## Observed real library checks

- Target host: isolated temporary fixtures on a remotely connected Linux host; no AEK changes deployed to Agent Runtime.
- Python: Import Linter `2.15`, installed with `pip install --target /tmp/aegkit-guard-libs import-linter==2.15`.
  - Clean sample: exit `0`.
  - Forbidden dependency `learning -> publishing`: exit `1` (correctly rejected).
  - Sibling dependency cycle: exit `1` (correctly rejected).
  - Repaired sample: exit `0`.
- TypeScript: Node `22.23.2`, npm `10.9.8`, dependency-cruiser `17`, and TypeScript `5`, installed in `/tmp/aegkit-ts-libs`.
  - Clean sample: exit `0`.
  - Runtime import across forbidden boundary: exit `1` (correctly rejected).
  - Type-only import across forbidden boundary: exit `1` (correctly rejected).
  - Repaired sample: exit `0`.

These tests exercised the **generated native checker contract shapes** with real underlying tools. They did not run an installed AEK Wheel on the remote host. The source repository's `tests/integration/test_real_adapters.py` is the independent, automated version of these fixtures and must still pass in hosted GitHub Actions before a public release is called verified.

## Not yet done

- Publish a new public GitHub repository (not supported by the connected GitHub actions available in this session).
- Observe the `real-adapters` GitHub Actions job and release-tag build.
- Open and pass a dedicated Agent Runtime adoption PR based on the clean GitHub `main` branch. The live VM working tree was dirty and detached, so no local edits were made.
- Enable branch ruleset requiring architecture and behavior checks.

## Reproduction

In the public repository, the CI workflow `.github/workflows/tests.yml` installs both adapters and sets `AEGKIT_REQUIRE_ADAPTERS=1` to prevent skipped checks from being treated as a pass. The target project CI must also install the original project's test dependencies.
