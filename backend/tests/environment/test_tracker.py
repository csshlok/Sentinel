from __future__ import annotations

import json
import os
import sys
from uuid import uuid4

import pytest

from backend.app.contracts.models import EnvironmentFact, EvidenceStatus
from backend.app.contracts.ports import EnvironmentPort
from backend.app.core.errors import AppError
from backend.app.environment.tracker import EnvironmentTracker
from backend.tests.support_kb import git, make_repo, write

CHANGE = uuid4()
CANARY = "kb-env-canary-SECRET-value-98765"


def fake_runner(outputs: dict[str, tuple[int | None, str]] | None = None):
    outputs = outputs or {}

    def run(argv, cwd):
        for needle, result in outputs.items():
            if needle in " ".join(argv):
                return result
        return 0, "1.2.3\n"

    return run


def tracker(**kw):
    kw.setdefault("environ", {"PATH": os.environ["PATH"]})
    kw.setdefault("runner", fake_runner())
    return EnvironmentTracker(**kw)


def facts(passport):
    return {f.key: f for f in passport.facts}


def test_conformance_and_serialization(tmp_path):
    repo = make_repo(tmp_path / "r")
    t = tracker()
    assert isinstance(t, EnvironmentPort)
    passport = t.capture(CHANGE, str(repo))
    assert passport.change_id == CHANGE and passport.schema_version == 1
    assert type(passport).model_validate_json(passport.model_dump_json()) == passport
    keys = [f.key for f in passport.facts]
    assert keys == sorted(keys)
    assert {"os.system", "python.version", "repo.manifests"} <= set(keys)


def test_identical_inputs_give_identical_passports_and_empty_drift(tmp_path):
    repo = make_repo(tmp_path / "r", {"package.json": "{}"})
    t = tracker(environ={"PATH": os.environ["PATH"], "NODE_ENV": "test"})
    a, b = t.capture(CHANGE, str(repo)), t.capture(CHANGE, str(repo))
    assert a.facts == b.facts and a.limitations == b.limitations
    drift = t.compare(a, b)
    assert not (drift.added or drift.removed or drift.changed or drift.unknown)
    assert drift.causal_attribution_available is False
    assert facts(a)["repo.manifests"].value == "package.json"
    assert facts(a)["env.NODE_ENV"].value == "test"


def test_tool_versions_paths_and_absent_tools(tmp_path):
    repo = make_repo(tmp_path / "r")
    t = tracker(tools={"python": ["--version"], "no-such-tool-zzz": ["--version"]},
                runner=fake_runner({"--version": (0, "\x1b[31mPython 9.9.9\x1b[0m\r\nextra\n")}))
    got = facts(t.capture(CHANGE, str(repo)))
    assert got["tool.python.version"].value == "Python 9.9.9"
    assert got["tool.python.path"].sensitive and got["tool.python.path"].value is None
    assert not any("no-such-tool-zzz" in key for key in got)


@pytest.mark.parametrize("result", [(1, "boom"), (0, "   \n"), (None, "")])
def test_unusable_tool_output_is_partial(tmp_path, result):
    repo = make_repo(tmp_path / "r")
    t = tracker(tools={"python": ["--version"]}, runner=fake_runner({"--version": result}))
    passport = t.capture(CHANGE, str(repo))
    assert facts(passport)["tool.python.version"].status is EvidenceStatus.PARTIAL
    assert passport.status is EvidenceStatus.PARTIAL
    assert any("usable version" in item for item in passport.limitations)


def test_runner_oserror_is_partial(tmp_path):
    repo = make_repo(tmp_path / "r")

    def boom(argv, cwd):
        raise OSError("private")

    t = tracker(tools={"python": ["--version"]}, runner=boom)
    passport = t.capture(CHANGE, str(repo))
    assert facts(passport)["tool.python.version"].status is EvidenceStatus.PARTIAL
    assert "private" not in passport.model_dump_json()


def test_collector_failure_is_isolated_and_reported(tmp_path):
    repo = make_repo(tmp_path / "r")

    def _collect_exploding(context):
        raise RuntimeError("secret detail")

    def _collect_good(context):
        return [context.tracker.plain("custom.key", "v")]

    t = tracker(collectors=[_collect_exploding, _collect_good])
    passport = t.capture(CHANGE, str(repo))
    assert [f.key for f in passport.facts] == ["custom.key"]
    assert passport.status is EvidenceStatus.PARTIAL
    assert any("exploding" in item for item in passport.limitations)
    assert "secret detail" not in passport.model_dump_json()


def test_duplicate_facts_keep_first(tmp_path):
    repo = make_repo(tmp_path / "r")

    def _collect_a(context):
        return [context.tracker.plain("dup", "first")]

    def _collect_b(context):
        return [context.tracker.plain("dup", "second")]

    passport = tracker(collectors=[_collect_a, _collect_b]).capture(CHANGE, str(repo))
    assert facts(passport)["dup"].value == "first"
    assert any("Duplicate" in item for item in passport.limitations)


def test_canary_secrets_never_appear(tmp_path):
    repo = make_repo(tmp_path / "r")
    git(repo, "remote", "add", "origin", f"https://user:{CANARY}@example.test/org/repo.git")
    env = {"PATH": os.environ["PATH"], "KB_ENV_CANARY_TOKEN": CANARY,
           "CUSTOM_NAME": CANARY, "NODE_ENV": "plain"}
    t = tracker(environ=env, sensitive_keys=("CUSTOM_NAME",), config_keys=("KB_ENV_CANARY_TOKEN",),
                runner=fake_runner({"remote.origin.url": (0, f"https://user:{CANARY}@example.test/org/repo.git\n")}))
    passport = t.capture(CHANGE, str(repo))
    blob = passport.model_dump_json() + repr(passport) + json.dumps(passport.model_dump(mode="json"))
    assert CANARY not in blob and "user:" not in blob
    got = facts(passport)
    assert got["env.KB_ENV_CANARY_TOKEN"].sensitive and got["env.CUSTOM_NAME"].sensitive
    assert got["git.remote.origin"].sensitive
    assert got["git.remote.origin.host"].value == "example.test"


def test_plain_value_containing_a_known_secret_is_scrubbed(tmp_path):
    repo = make_repo(tmp_path / "r")
    env = {"PATH": os.environ["PATH"], "KB_TOKEN_X": CANARY}

    def _collect_leaky(context):
        return [context.tracker.plain("leaky", f"prefix {CANARY} suffix")]

    passport = tracker(environ=env, collectors=[_collect_leaky]).capture(CHANGE, str(repo))
    assert CANARY not in passport.model_dump_json()
    assert "[REDACTED]" in facts(passport)["leaky"].value


def test_scp_style_and_invalid_remote_hosts():
    assert EnvironmentTracker._host("git@github.com:org/repo.git") == "github.com"
    assert EnvironmentTracker._host("ssh://git@host.example/x") == "host.example"
    assert EnvironmentTracker._host("/local/path") is None


def test_repository_configuration_is_read_from_real_git(tmp_path):
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "core.autocrlf", "input")
    git(repo, "remote", "add", "origin", "git@example.test:org/repo.git")
    t = EnvironmentTracker(environ={"PATH": os.environ["PATH"]}, tools={})
    got = facts(t.capture(CHANGE, str(repo)))
    assert got["git.core.autocrlf"].value == "input"
    assert got["git.remote.origin.host"].value == "example.test"
    assert "org/repo" not in json.dumps([f.model_dump(mode="json") for f in got.values()])


def test_missing_git_is_reported(tmp_path):
    repo = make_repo(tmp_path / "r")
    t = EnvironmentTracker(environ={"PATH": ""}, tools={}, runner=fake_runner())
    passport = t.capture(CHANGE, str(repo))
    assert any("Git is unavailable" in item for item in passport.limitations)


def test_drift_classification(tmp_path):
    repo = make_repo(tmp_path / "r")
    t = tracker()
    base = t.capture(CHANGE, str(repo))

    def custom(*items):
        def _collect_x(context):
            return list(items)
        return tracker(collectors=[_collect_x])

    left = custom(EnvironmentFact(key="same", value="1"), EnvironmentFact(key="edit", value="1"),
                  EnvironmentFact(key="gone", value="1"), EnvironmentFact(key="fp", fingerprint="a" * 64,
                                                                         sensitive=True),
                  EnvironmentFact(key="bad", status=EvidenceStatus.PARTIAL),
                  EnvironmentFact(key="lost-partial", status=EvidenceStatus.UNSUPPORTED)
                  ).capture(CHANGE, str(repo))
    right = custom(EnvironmentFact(key="same", value="1"), EnvironmentFact(key="edit", value="2"),
                   EnvironmentFact(key="new", value="1"), EnvironmentFact(key="fp", fingerprint="b" * 64,
                                                                         sensitive=True),
                   EnvironmentFact(key="bad", value="ok"),
                   EnvironmentFact(key="new-partial", status=EvidenceStatus.UNSUPPORTED)
                   ).capture(CHANGE, str(repo))
    drift = t.compare(left, right)
    assert [f.key for f in drift.added] == ["new"]
    assert [f.key for f in drift.removed] == ["gone"]
    assert [f.key for f in drift.changed] == ["edit", "fp"]
    assert [f.key for f in drift.unknown] == ["bad", "lost-partial", "new-partial"]
    assert drift.baseline_id == left.id and drift.current_id == right.id
    assert t.compare(base, base).changed == []
    assert t.compare(left, right) == drift


def test_invalid_inputs(tmp_path):
    with pytest.raises(ValueError):
        EnvironmentTracker(fingerprint_key=b"short")
    with pytest.raises(ValueError):
        EnvironmentTracker(fingerprint_key="not-bytes" * 4)
    t = tracker()
    for bad in (str(tmp_path / "missing-private"), "x\0y"):
        with pytest.raises(AppError) as info:
            t.capture(CHANGE, bad)
        assert info.value.code == "INVALID_REPOSITORY_PATH" and "private" not in info.value.message
    file = tmp_path / "f"
    file.write_text("x")
    with pytest.raises(AppError):
        t.capture(CHANGE, str(file))


def test_fingerprints_are_keyed_and_stable():
    a = EnvironmentTracker(fingerprint_key=b"k" * 16).fingerprint("k", "v")
    b = EnvironmentTracker(fingerprint_key=b"k" * 16).fingerprint("k", "v")
    c = EnvironmentTracker(fingerprint_key=b"z" * 16).fingerprint("k", "v")
    assert a == b != c and len(a) == 64


def test_value_normalization_and_bound(tmp_path):
    repo = make_repo(tmp_path / "r")
    env = {"PATH": os.environ["PATH"], "TZ": "  UTC\t\x07 zone  ", "LANG": "", "CI": "x" * 2000}
    got = facts(EnvironmentTracker(environ=env, tools={}, runner=fake_runner()).capture(CHANGE, str(repo)))
    assert got["env.TZ"].value == "UTC zone"
    assert got["env.LANG"].value == "(empty)"
    assert len(got["env.CI"].value) == 512


def test_real_windows_or_posix_smoke(tmp_path):
    repo = make_repo(tmp_path / "r", {"pyproject.toml": "[project]\nname='x'\n"})
    passport = EnvironmentTracker(tools={"git": ["--version"], "python": ["--version"]}).capture(
        CHANGE, str(repo))
    got = facts(passport)
    assert got["tool.git.version"].value.startswith("git version")
    assert got["python.version"].value == sys.version.split()[0]
    assert "repo.manifests" in got and got["repo.manifests"].value == "pyproject.toml"
    # The real environment's secrets never surface.
    for value in os.environ.values():
        if len(value) >= 12 and "TOKEN" in "".join(k for k, v in os.environ.items() if v == value).upper():
            assert value not in passport.model_dump_json()


def test_drift_after_real_repository_change(tmp_path):
    repo = make_repo(tmp_path / "r")
    t = EnvironmentTracker(tools={}, environ={"PATH": os.environ["PATH"]})
    base = t.capture(CHANGE, str(repo))
    write(repo, "package.json", "{}")
    write(repo, "requirements.txt", "x==1")
    current = t.capture(CHANGE, str(repo))
    drift = t.compare(base, current)
    assert [f.key for f in drift.changed] == ["repo.manifests"]
    assert drift.changed[0].value == "package.json,requirements.txt"
