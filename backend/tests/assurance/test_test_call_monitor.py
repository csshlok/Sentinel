"""Runtime caller evidence catches dynamic reaches into changed test modules."""

from __future__ import annotations

import json
import subprocess
import sys
from uuid import uuid4
from pathlib import Path

import pytest

from backend.app.assurance.test_call_monitor import assess_record, prepare_monitor
from backend.app.assurance.diff_coverage import evaluate_report
from backend.app.contracts.models import DiffCoverageRequest, DiffCoverageResult, DiffCoverageRule, utc_now


@pytest.mark.parametrize("production", [
    "from importlib import import_module as im\ndef price(x):\n"
    "    return im('tests.test_helpers').test_compute(x)\n",
    "import sys\ndef price(x):\n"
    "    return sys.modules['tests.test_helpers'].test_compute(x)\n",
    "from sys import modules\ndef price(x):\n"
    "    return modules['tests.test_helpers'].test_compute(x)\n",
    "import builtins\ndef price(x):\n"
    "    imp = getattr(builtins, '__imp' + 'ort__')\n"
    "    return imp('tests.test_helpers', fromlist=['x']).test_compute(x)\n",
])
def test_monitor_records_production_call_into_changed_test(tmp_path: Path,
                                                          production: str) -> None:
    root = tmp_path / "tree"
    scratch = tmp_path / "scratch"
    (root / "tests").mkdir(parents=True)
    scratch.mkdir()
    (root / "tests/__init__.py").write_text("", encoding="utf-8")
    (root / "tests/test_helpers.py").write_text(
        "def test_compute(x=0):\n    if x > 100:\n        return -1\n    return x\n",
        encoding="utf-8")
    (root / "module.py").write_text(production, encoding="utf-8")
    (root / "tests/test_price.py").write_text(
        "import tests.test_helpers\nfrom module import price\n"
        "def test_price():\n    assert price(5) == 5\n", encoding="utf-8")
    argv, record_name = prepare_monitor(
        scratch, root, ["tests/test_helpers.py"],
        [sys.executable, "-X", f"pycache_prefix={scratch / 'pycache'}",
         "-m", "coverage", "run", "-m", "pytest", "-q", "tests/test_price.py",
         "-o", "addopts=", f"--junitxml={scratch / 'junit.xml'}"])
    (scratch / record_name).write_text(json.dumps({
        "schema": 1, "backend": "sys.monitoring",
        "changed_tests": ["tests/test_helpers.py"], "violations": [],
    }), encoding="utf-8")
    run = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    record = (scratch / record_name).read_bytes()
    assert assess_record(record, ["tests/test_helpers.py"]) is not None
    violations = json.loads(record)["violations"]
    assert any("module.py:" in item and "tests/test_helpers.py:" in item
               for item in violations)


def test_monitor_allows_legitimate_test_caller(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    scratch = tmp_path / "scratch"
    (root / "tests").mkdir(parents=True)
    scratch.mkdir()
    (root / "tests/__init__.py").write_text("", encoding="utf-8")
    (root / "tests/test_helpers.py").write_text(
        "def test_compute(x=0):\n    return x\n", encoding="utf-8")
    (root / "tests/test_price.py").write_text(
        "from tests.test_helpers import test_compute\n"
        "def test_price():\n    assert test_compute(5) == 5\n", encoding="utf-8")
    argv, record_name = prepare_monitor(
        scratch, root, ["tests/test_helpers.py"],
        [sys.executable, "-X", f"pycache_prefix={scratch / 'pycache'}",
         "-m", "coverage", "run", "-m", "pytest", "-q", "tests/test_price.py",
         "-o", "addopts=", f"--junitxml={scratch / 'junit.xml'}"])
    run = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert assess_record((scratch / record_name).read_bytes(),
                         ["tests/test_helpers.py"]) is None


def test_monitor_records_production_import_of_changed_test_module(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    scratch = tmp_path / "scratch"
    (root / "tests").mkdir(parents=True)
    scratch.mkdir()
    (root / "tests/__init__.py").write_text("", encoding="utf-8")
    (root / "tests/test_helpers.py").write_text("VALUE = 5\n", encoding="utf-8")
    (root / "module.py").write_text(
        "import importlib\n"
        "def price():\n"
        "    return importlib.import_module('tests.test_helpers').VALUE\n",
        encoding="utf-8")
    (root / "tests/test_price.py").write_text(
        "from module import price\n"
        "def test_price():\n    assert price() == 5\n", encoding="utf-8")
    argv, record_name = prepare_monitor(
        scratch, root, ["tests/test_helpers.py"],
        [sys.executable, "-X", f"pycache_prefix={scratch / 'pycache'}",
         "-m", "coverage", "run", "-m", "pytest", "-q", "tests/test_price.py",
         "-o", "addopts=", f"--junitxml={scratch / 'junit.xml'}"])
    run = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    record = (scratch / record_name).read_bytes()
    assert any("module.py:" in item and "tests/test_helpers.py:" in item
               for item in json.loads(record)["violations"])


@pytest.mark.parametrize("driver", ["send", "throw"])
def test_monitor_records_production_generator_resume(tmp_path: Path, driver: str) -> None:
    root = tmp_path / "tree"
    scratch = tmp_path / "scratch"
    (root / "tests").mkdir(parents=True)
    scratch.mkdir()
    (root / "tests/__init__.py").write_text("", encoding="utf-8")
    (root / "tests/test_helpers.py").write_text(
        "import builtins\n"
        "def test_prime():\n"
        "    def calc():\n"
        "        try:\n"
        "            x = yield\n"
        "        except ValueError:\n"
        "            x = 5\n"
        "        yield x\n"
        "    builtins.SENTINEL_CALC = calc()\n"
        "    next(builtins.SENTINEL_CALC)\n", encoding="utf-8")
    action = "send(5)" if driver == "send" else "throw(ValueError())"
    (root / "module.py").write_text(
        "import builtins\ndef price():\n"
        f"    return builtins.SENTINEL_CALC.{action}\n", encoding="utf-8")
    (root / "tests/test_price.py").write_text(
        "from tests.test_helpers import test_prime\nfrom module import price\n"
        "def test_price():\n    test_prime()\n    assert price() == 5\n", encoding="utf-8")
    argv, record_name = prepare_monitor(
        scratch, root, ["tests/test_helpers.py"],
        [sys.executable, "-X", f"pycache_prefix={scratch / 'pycache'}",
         "-m", "coverage", "run", "-m", "pytest", "-q", "tests/test_price.py",
         "-o", "addopts=", f"--junitxml={scratch / 'junit.xml'}"])
    run = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    record = (scratch / record_name).read_bytes()
    assert any("module.py:" in item and "tests/test_helpers.py:" in item
               for item in json.loads(record)["violations"]), run.stderr


@pytest.mark.parametrize("launch,reason", [
    ("thread", "non-main thread"),
    ("atexit", "outside the pytest session stack"),
])
def test_monitor_requires_main_thread_and_session_root(
        tmp_path: Path, launch: str, reason: str) -> None:
    root = tmp_path / "tree"
    scratch = tmp_path / "scratch"
    (root / "tests").mkdir(parents=True)
    scratch.mkdir()
    (root / "tests/__init__.py").write_text("", encoding="utf-8")
    (root / "tests/test_helpers.py").write_text(
        "def test_compute():\n    return 5\n", encoding="utf-8")
    call = ("import threading\n"
            "    worker = threading.Thread(target=test_compute)\n"
            "    worker.start()\n    worker.join()\n") if launch == "thread" else (
            "import atexit\n    atexit.register(test_compute)\n")
    (root / "tests/test_price.py").write_text(
        "from tests.test_helpers import test_compute\n"
        "def test_price():\n    " + call, encoding="utf-8")
    argv, record_name = prepare_monitor(
        scratch, root, ["tests/test_helpers.py"],
        [sys.executable, "-X", f"pycache_prefix={scratch / 'pycache'}",
         "-m", "coverage", "run", "-m", "pytest", "-q", "tests/test_price.py",
         "-o", "addopts=", f"--junitxml={scratch / 'junit.xml'}"])
    run = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert reason in assess_record((scratch / record_name).read_bytes(),
                                   ["tests/test_helpers.py"])


def test_profile_fallback_record_is_unknown() -> None:
    record = json.dumps({"schema": 1, "backend": "sys.setprofile",
                         "changed_tests": ["tests/test_helpers.py"],
                         "violations": []}).encode()
    assert "cannot observe all threads" in assess_record(record, ["tests/test_helpers.py"])


def test_monitor_evidence_is_fail_closed() -> None:
    assert "missing" in assess_record(None, ["tests/test_helpers.py"])
    assert "unreadable" in assess_record(b"not json", ["tests/test_helpers.py"])


def test_required_evaluator_needs_clean_monitor_record(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "module.py").write_text("def price():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests/test_helpers.py").write_text(
        "def test_real():\n    assert True\n", encoding="utf-8")
    baseline, tested = uuid4(), uuid4()
    initial = DiffCoverageResult(
        change_id=uuid4(), baseline_checkpoint_id=baseline, tested_checkpoint_id=tested,
        head_sha="a" * 40, status_digest="b" * 64, contract_digest="c" * 64,
        started_at=utc_now(), completed_at=utc_now(), collector_status="COLLECTED",
        checks_passed=True, diff_exercised="UNKNOWN", freshness="CURRENT",
    )
    request = DiffCoverageRequest(
        baseline_checkpoint_id=baseline, tested_checkpoint_id=tested,
        interpreter_path=sys.executable,
        rule=DiffCoverageRule(required=True, minimum_percent=80),
    )
    common = dict(result=initial, changed={"module.py": {2}},
                  excluded={"tests/test_helpers.py": "test code"},
                  report={"files": {"module.py": {"executed_lines": [2],
                                                  "missing_lines": []}}},
                  root=tmp_path, rule=request,
                  collected_test_paths={"tests/test_helpers.py"},
                  excluded_changed_lines={"tests/test_helpers.py": {1, 2}},
                  monitor_requested=True)
    missing = evaluate_report(**common, monitor_record=None)
    assert missing.diff_exercised == "UNKNOWN" and missing.gate_satisfied is False
    clean = json.dumps({"schema": 1, "backend": "sys.monitoring",
                        "changed_tests": ["tests/test_helpers.py"],
                        "violations": []}).encode()
    passed = evaluate_report(**common, monitor_record=clean)
    assert passed.diff_exercised == "PASS" and passed.gate_satisfied is True
    violated = json.dumps({"schema": 1, "backend": "sys.monitoring",
                           "changed_tests": ["tests/test_helpers.py"],
                           "violations": ["module.py:2 -> tests/test_helpers.py:1"]}).encode()
    blocked = evaluate_report(**common, monitor_record=violated)
    assert blocked.diff_exercised == "UNKNOWN" and blocked.gate_satisfied is False
    assert any("module.py:2" in reason for reason in blocked.reasons)


