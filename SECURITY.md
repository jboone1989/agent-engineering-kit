# Security policy

AEK is a local command-line development tool. It executes test commands from
`.agent-engineering/policy.json`, which must be treated as executable project
configuration, **not** as untrusted input. Review policy edits as code changes.

Do not run a guard from an untrusted pull request with deployment or publication
credentials. Use GitHub-hosted read-only PR jobs, limit workflow permissions,
and protect policy, guard, and release workflow changes via repository rules.

No telemetry, network client, or credentials storage are built into the core.
Native language adapters (`import-linter`, `dependency-cruiser`) must be
installed separately. Their supply chains should be reviewed and pinned by
projects before production adoption.

For a suspected vulnerability, report privately through the eventual GitHub
repository's Security Advisories once the repository exists. Do not post
secrets or sensitive proof-of-concept data in public issues.
