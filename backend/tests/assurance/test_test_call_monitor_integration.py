"""End-to-end changed-test caller gate through the confined coverage collector."""

from __future__ import annotations

import sys
import site
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.assurance.diff_coverage import collect_diff_coverage
from backend.app.contracts.models import (ChangeView, DiffCoverageRequest, DiffCoverageResult,
                                          DiffCoverageRule, ReviewState, utc_now)
from backend.app.git.state import GitStateTracker
from backend.tests.support_checks import host_check_boxes
from backend.tests.support_kb import make_repo, write


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
    "import functools\nfrom sys import modules\nfrom _pytest.runner import CallInfo\n"
    "def price(x):\n"
    "    fn = functools.partial(modules['tests.test_helpers'].test_compute, x)\n"
    "    return CallInfo.from_call(fn, when='call').result\n",
    "from sys import modules\nfrom _pytest.runner import CallInfo\n"
    "def price(x):\n"
    "    callback = modules['tests.test_helpers'].test_compute\n"
    "    return CallInfo.from_call(lambda: callback(x), when='call').result\n",
], ids=["m5a", "m5b", "m6a", "m6b", "m7a", "callback-relay"])
def test_required_diff_rejects_production_call_into_changed_test(tmp_path: Path,
                                                                 production: str) -> None:
    result = _measure_changed_test(tmp_path, production)
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    assert any("Repository production frame reached changed test module "
               "(including callbacks):" in reason and "module.py:" in reason
               and "tests/test_helpers.py:" in reason for reason in result.reasons)


def test_required_diff_allows_legitimate_added_test(tmp_path: Path) -> None:
    result = _measure_changed_test(tmp_path, "def price(x):\n    return x\n")
    assert result.diff_exercised == "PASS", result.reasons
    assert result.gate_satisfied is True


def _measure_changed_test(tmp_path: Path, production: str) -> DiffCoverageResult:
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
        "module.py": "def old():\n    return 1\n",
        "tests/__init__.py": "",
        "tests/test_old.py": "from module import old\n"
                             "def test_old():\n    assert old() == 1\n",
    })
    change = ChangeView(id=uuid4(), title="monitor", intent="measure",
                        repository_path=str(root), created_at=utc_now(),
                        updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "module.py", "def old():\n    return 1\n\n" + production)
    write(root, "tests/test_helpers.py",
          "def test_compute(x=0):\n    if x > 100:\n"
          "        return -1\n    return x\n")
    write(root, "tests/test_price.py",
          "import tests.test_helpers\nfrom module import price\n"
          "def test_price():\n    assert price(5) == 5\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    request = DiffCoverageRequest(
        baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        interpreter_path=sys.executable, test_args=["-q"],
        rule=DiffCoverageRule(required=True, minimum_percent=80,
                              interpreter_path=sys.executable),
    )
    boxes, _ = host_check_boxes(tmp_path / "boxes")
    # The host harness supplies a minimal environment. This local Python has
    # coverage and pytest in its user site, so expose those tools to the fake
    # host child; real check boxes use a runtime snapshot instead.
    base_environment = boxes._platform.base_environment
    def tools_environment(*args, **kwargs):
        environment = base_environment(*args, **kwargs)
        environment["PYTHONPATH"] = site.getusersitepackages()
        return environment
    boxes._platform = replace(boxes._platform, base_environment=tools_environment)
    return collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                 request=request, checks=boxes)
