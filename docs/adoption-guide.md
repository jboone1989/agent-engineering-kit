# Adoption: existing repository (without a rewrite)

## 0. Inventory first

Map actual package directories, public interfaces, persistent state and test commands.
Don't classify a boundary from a filename alone: take ownership and runtime calls into account.

## 1. Start with a denylist (low-risk adoption)

Example: an independent `learning` module must never depend on `publishing`.

```shell
aegkit init . --language python --package myagent \
  --forbid learning:publishing --test 'python -m pytest -q'
```

Initial setup does not write over `AGENTS.md`, CI, or an existing policy; merge
conflicting files manually. Install `import-linter` and the real project test deps.
Run `doctor`, `render-config` and a real `check` against the existing codebase.

## 2. Move to strict allowlist once ownership is understood

In `.agent-engineering/policy.json` add `modules` and `allowed_dependencies`.
The guard rejects cross-dependencies between declared modules unless permitted.
It also rejects any new top-level source module not included in `modules`, unless
explicitly added to `unmanaged_modules` (or `module_coverage` is set to `off`).

When a module already violates a rule, don't delete the rule to force green.
Keep the initial denylist small, remove historical violations, then expand the
contract. Do not treat `unmanaged_modules` as a dumping ground.

## 3. Protect the gate from agent edits

- CI must run both language boundary checks and behavior tests.
- Make `quality-gate` required in the repository ruleset.
- Require a human review for edits to `.agent-engineering/*`, `AGENTS.md`,
  `.github/workflows/*` and project architecture files.
- Consider GitHub CODEOWNERS for these paths; an example is below.
- If a policy really needs to change, explain the new ownership and test the new boundary.

## 4. Verify that the contract matters

Introduce a temporary forbidden import in a throwaway branch. `check` should
fail. Remove it; `check` should pass. If not, the policy is not enforced.

Only do this on a dedicated branch, not in production code.

## 5. Success metric

Over several PRs, observe whether public API changes require fewer unrelated
module edits, whether cycles stop increasing, and whether a module can be tested
with its adapters replaced. These are more meaningful than counting classes.

### CODEOWNERS example (edit GitHub owner)

```text
# .github/CODEOWNERS
/.agent-engineering/ @your-org/architecture-maintainers
/AGENTS.md @your-org/architecture-maintainers
/ARCHITECTURE.md @your-org/architecture-maintainers
/.github/workflows/ @your-org/architecture-maintainers
```
