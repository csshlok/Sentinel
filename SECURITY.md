# Security reporting

Use [GitHub's private vulnerability reporting page](https://github.com/csshlok/Sentinel/security/advisories/new) to report a vulnerability. If that page is unavailable, [open a minimal issue](https://github.com/csshlok/Sentinel/issues/new) asking for a private contact channel. Do not include exploit steps, secrets, or affected repository contents in a public issue.

Please include the Sentinel version (`sentinel --version`), Windows version, affected feature, reproduction steps, and whether the issue requires a local user, a repository under agent control, or a hostile Passport bundle. Redact credentials and private repository data. Maintainers have not committed to a response time or a coordinated disclosure schedule.

## Threat model and current limits

Sentinel handles untrusted agent output, repository contents, Git metadata, and imported Passport bundles. It uses scoped authority checks, supervised processes, Git and journal evidence, and signed exports. Those controls have distinct limits:

- The built-in Claude profile attempts a verified Windows AppContainer launch. The generic profile uses a restricted token and Job Object; that profile does not isolate filesystem or network access. The built-in Codex profile currently refuses to launch. A boundary claim in Passport v2 remains `UNKNOWN` until the observed execution facts are bound to it.
- Software-provider signing keys are protected by Windows CNG export policy, but another process running as the same user may be able to extract them through DPAPI. A TPM provider offers a stronger hardware boundary when available. A valid signature proves integrity under the displayed key, not that the host or signer was uncompromised.
- Diff coverage measures executed changed Python lines. Execution does not prove assertion quality or correctness. Unknown mapping, freshness, or collection results must remain `UNKNOWN` or `STALE` and cannot satisfy a required rule.
- The journal hash chain detects edits to recorded history, but a process with authority over the local database, key, and runtime can replace the whole evidence set. The operator must establish trust in a public-key fingerprint separately.
- Direct build, runtime and test dependencies are pinned in `pyproject.toml`; transitive dependencies are not locked and may resolve differently between installs.
- GitHub Check publication is bound to an observed PR head and policy revision at publication time. A later push or policy change makes earlier results stale; GitHub's presentation is not the source of evidence. Verify a downloaded `.sentinel` bundle independently with `sentinel verify`.
- Real AppContainer tests depend on Windows facilities and a locally usable Node executable. The default Windows CI suite runs them unless they skip for missing prerequisites; hosted-runner coverage of the real boundary has not yet been demonstrated. Hosted runners without a usable TPM exercise disposable software-provider test keys. Production signing still fails closed when the Platform provider reports `NTE_DEVICE_NOT_READY`, because that status might hide an existing TPM identity.

Do not use this pre-release software as the only control protecting valuable credentials or repositories.
