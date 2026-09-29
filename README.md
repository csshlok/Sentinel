# Sentinel

Sentinel is a pre-release, local-first Windows runtime for recording evidence about changes made with coding agents. It has a FastAPI backend, CLI, Textual interface, and Electron desktop app. The repository is under active development; there is no installer, code signing, or production support commitment.

Sentinel stores Changes, Git checkpoints, execution records, assurance results, and a hash-chained journal. A Change Passport can package selected records for offline verification. These records describe what Sentinel observed at a particular time. They do not establish that a change is correct or that the host was uncompromised.

## Execution boundaries

Launch behavior depends on the built-in agent profile:

| Profile | Current behavior |
| --- | --- |
| `claude` | Attempts a verified Windows AppContainer launch with a dedicated workspace. The launch fails closed if the required boundary cannot be established. |
| `generic` | Uses a restricted Windows token and a supervised Job Object. The token reduces privileges but provides no filesystem or network isolation. |
| `codex` | Refuses to launch because its AppContainer runtime profile has not been validated. |

Process-tree observation can miss a descendant that starts and exits between polls. Git checkpoints do not track arbitrary writes outside the repository. Review the actual launch facts for a run before drawing a boundary conclusion. Passport v2 currently records `execution_boundary: UNKNOWN` until those facts are bound into the signed payload; a preset requiring an observed AppContainer boundary therefore denies.

## Assurance and Passports

Python diff assurance compares changed executable lines with coverage.py execution data. It reports checks passed, diff exercised, and freshness as separate claims. An executed line does not prove an assertion checked its behavior; assertion quality is not measured. Unsupported source, missing collection data, stale repository state, and unreported continuation lines yield `UNKNOWN` or `STALE` as appropriate. A required rule does not pass on unknown evidence.

Passport v1 uses the existing Ed25519 path. Passport v2 issues an ES256 signature over a canonical manifest in a portable `change-<id>.sentinel` bundle. The v2 signing key is created through Windows CNG, using the Platform Crypto Provider when available and the Software Key Storage Provider otherwise. The private key is not exported by Sentinel; a same-user process may still be able to extract a software-provider key through DPAPI. The bundle names its provider and signer fingerprint. Recipients must establish trust in that fingerprint themselves, and revocation or an unknown signer makes verification indeterminate. A signature proves integrity under that key, not that the underlying evidence is complete or truthful.

The bundle includes a text-based HTML/SVG card and can be checked without a Sentinel database:

```text
sentinel passport export <change-id>
sentinel verify <bundle.sentinel> --json
```

The verifier returns exit code 0 for valid, 1 for invalid, 2 for indeterminate, and 3 for a usage error. The card and verifier distinguish checks, diff execution, freshness, boundary, and limitations. Older v2 bundles remain verifiable.

## GitHub and policy

`sentinel github app create` starts a local, one-time callback to configure a GitHub App for a user or organization. `sentinel github app status` reports installation state; `sentinel github check <change-id>` publishes a Check Run for the observed PR head. If an App is declined, the existing token path can publish visibly lesser commit statuses. A new push or policy change makes the prior result stale. GitHub presentation is not the signed evidence; download and verify the Passport bundle to inspect its claims.

Versioned `strict`, `standard`, and `docs-only` policy presets evaluate persisted Change evidence and name each unmet requirement. Unknown evidence denies. Preset selections and decisions are included in new Passport v2 payloads. The preset decision is available through the API, but its hook into the lifecycle transition gate is still pending; do not treat the preset result as an enforced release gate yet. Confined-check and observed AppContainer claims remain `UNKNOWN` until their structured evidence is wired in.

## Development

Python 3.12 or newer and Windows are required for the real execution paths. Install the package and pinned test dependencies, then run the suite:

```text
python -m pip install -e ".[test,tui]"
python -m pytest -q
sentinel --version
```

The [Windows CI workflow](.github/workflows/ci.yml) runs the default Python suite on pushes and pull requests. Real AppContainer tests require Windows facilities and a usable Node executable; hosted-runner coverage of that boundary has not yet been demonstrated. Live GitHub tests are opt-in. See [SECURITY.md](SECURITY.md) for reporting and trust limits.

No license has been selected yet. Contact the repository owner before reusing or distributing this code.
