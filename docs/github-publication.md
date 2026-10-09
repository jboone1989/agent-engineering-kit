# GitHub publication and required checks

AEK is an independent open-source candidate, not a public GitHub repository until publishing has been verified. **Never paste GitHub tokens or secrets into the chat or repository.** Scripts use an authenticated [GitHub CLI](https://cli.github.com/) locally.

## Publish as a standalone public repository

1. Review the repository's tracked files, especially LICENSE, README, SECURITY.md and all workflows. Ensure there are no credentials, local caches, or company-private source files.
2. Install and authenticate `gh` to the intended GitHub account (`gh auth login`). The connection needs permission to create a public repository.
3. From this Git checkout, preview:

```bash
python scripts/publish_public.py --owner YOUR_GITHUB_LOGIN
```

4. Only when ready to make these reviewed sources public, run:

```bash
python scripts/publish_public.py --owner YOUR_GITHUB_LOGIN --apply
```

This creates **one new public repository** named `agent-engineering-kit` from the **clean current `main` commit**, pushes the commit, and verifies that GitHub reports visibility `PUBLIC`. It intentionally refuses to overwrite an existing repository. This is not a PyPI release and does not change any connected business project or server service.

## Run CI on GitHub before setting required checks

Wait for the repository's GitHub Actions jobs to execute in the new public repository. Its workflow has a Python version matrix, real Python/TypeScript adapters, and packaging tests. The matrix produces its own job names; **inspect the actual completed check names in GitHub before selecting required contexts**. Do not blindly reuse job names from another project.

## Apply required status checks to the public kit

With repository administration permission, preview the rule using **actual hosted job names**:

```bash
python scripts/enforce_checks.py \
  --repo YOUR_GITHUB_LOGIN/agent-engineering-kit \
  --checks 'test (3.10)' 'test (3.12)' 'real-adapters' 'package'
```

The names above illustrate what GitHub might report; copy exact names from the live checks. After reviewing the JSON and confirming all checks have passed, run the same command with `--apply`. The script **creates** one active main-branch Ruleset and refuses to overwrite a same-named rule. It requires the branch to be up to date and all named checks to pass. It makes no bypass exemptions. It does not independently guarantee that all changes flow through pull requests—configure PR-only rules if required by your organization's policy.

### Agent Runtime example (verified CI job names, 2026-10-09)

```bash
python scripts/enforce_checks.py \
  --repo jboone1989/agent-runtime \
  --checks 'Enforce module boundaries' 'Full regression' 'Platform boundary suite' 'pytest'
```

Add `--apply` only if the repository's GitHub plan supports Rulesets for private repositories and an authorized administrator has checked the proposal. GitHub Free Rulesets support public repositories; private repositories require an eligible paid GitHub plan. This example does **not** imply Agent Runtime already has a Ruleset.

## Verify after applying

Inspect **Settings → Rules → Rulesets** or query:

```bash
gh api repos/OWNER/REPO/rulesets
```

Check `enforcement: active`, the exact `refs/heads/main` target and all expected `required_status_checks`. Open a disposable PR deliberately violating a project policy and confirm the required check fails and the merge is blocked; remove the violation and verify the check passes again. Do not disable CI checks merely to get a green result.

## Current limitations

The helper scripts prepare authenticated GitHub actions; they do not themselves provide credentials or bypass GitHub permissions, account login, plan limitations or approval gates. Publishing the source and installing Rulesets are separate steps. Any failure must remain visible; do not claim publication or protection until GitHub confirms it.
