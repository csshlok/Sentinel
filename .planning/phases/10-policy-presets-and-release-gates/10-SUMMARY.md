# Phase 10 summary

## Delivered

- P-01–P-03: `strict`, `standard`, and `docs-only` preset rules are deterministic, versioned, and default-deny. They name failed checks, coverage, freshness, confined checks, boundary, and docs-path requirements. Missing and unknown evidence denies.
- P-04: Change Contract schema v3 persists preset selection. New Passport v2 payloads sign the preset name, version, decision, denial reasons, and product version. Older v2 bundles still verify. The policy API evaluates persisted evidence without caller-provided facts.
- R-01/R-02: Direct build, runtime and test dependencies are pinned in `pyproject.toml`; transitive dependencies are not locked. An editable build dry run completed. Package metadata, `GET /api/v1/version`, `sentinel --version`, and new Passport payloads report `0.1.0` from the same package metadata source.
- R-03: `.github/workflows/ci.yml` runs `python -m pytest -q` on `windows-latest` for every push and pull request. The workflow installs the pinned test and TUI extras. Real AppContainer hosted-runner verification remains unproven.
- R-04/R-05: `SECURITY.md` gives a reporting route and current trust limits. README now describes the actual Claude, generic, and Codex runtime profiles; it removes stale test/API counts and unqualified isolation claims.
- R-06: No LICENSE was added, by user decision.

## Verification

Focused slices passed after each task. The first full-suite attempt exposed a stale v1 contract-digest test expectation: it included two optional schema-v3 preset fields that the production digest deliberately omits for v1. Commit `a262d21` updated that expectation; the focused assurance/policy slice passed 26 tests. The first hosted CI run also found a TPM-less runner reporting `NTE_DEVICE_NOT_READY`. Production signing must treat that ambiguous status as an error because it might hide an existing TPM key. Commit `e4c6faa` uses disposable software-provider keys inside the CI test process only. The hosted run exposed a fixture-order issue; `465faf4` moved setup ahead of module-scoped bundle fixtures. The affected Passport/CLI slice passed **59 tests** on `465faf4`.

The full local suite on `e4c6faa` completed **1,435 passed, 7 skipped, 0 failed, 2 warnings in 1705.04s (28m25s)**. Later commits change hosted test-fixture order and the isolated build-backend pin; the 59-test affected slice and dependency pin test passed, and an editable build dry run succeeded. Hosted CI [run 36619252644](https://github.com/csshlok/Sentinel/actions/runs/36619252644) completed with no Codex-owned failures or errors, but seven Claude-owned tests failed. Final hosted [run 36620065765](https://github.com/csshlok/Sentinel/actions/runs/36620065765) on `9f60b69` completed with nine failures: the same seven plus two TUI worker-flow cases. There were no Codex-owned test failures or errors. CI remains red.

## Open handoffs and limitations

- Claude-owned lifecycle code has not yet consumed the persisted preset decision. The API and Passport report `DENY` accurately, but the preset is not yet an enforced transition gate. Request is in `COORDINATION.md`.
- Hosted-runner tests failed in the plain-Git hook positive control, ACL shape, symlink privilege, and several real AppContainer execution scenarios. A workspace hostile-config positive control missed `filter-clean`; two TUI worker-flow cases also failed on the final run. Requests with exact paths and Actions runs are in `COORDINATION.md`; the CI gate remains red until they are resolved.
- Signed Passport `execution_boundary` and `confined_checks` remain `UNKNOWN` until structured facts from Claude-owned execution and verification phases are available.
- Phase 6 N3-01 independent re-review remains requested. The user chose exact-line coverage credit and `UNKNOWN` for unreported continuation lines in N3-02.
- The user has not chosen a license. The README stash `stash@{0}` was neither applied nor dropped.
