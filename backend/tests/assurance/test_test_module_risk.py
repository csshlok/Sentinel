"""Changed tests must not shelter unmeasured production logic."""

from pathlib import Path

import pytest

from backend.app.assurance.diff_coverage import _test_module_risk


@pytest.mark.parametrize("production", [
    "from importlib import import_module as im\ndef price(x):\n    return im('tests.test_helpers').TestHelpers.compute(x)\n",
    "import sys\ndef price(x):\n    return sys.modules['tests.test_helpers'].TestHelpers.compute(x)\n",
])
def test_changed_test_class_helper_and_dynamic_access_are_unknown(tmp_path: Path,
                                                                  production: str) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_helpers.py").write_text(
        "class TestHelpers:\n    @staticmethod\n    def compute(x):\n"
        "        if x > 100:\n            return -1\n        return x\n"
        "    def test_dummy(self):\n        assert True\n", encoding="utf-8")
    (tmp_path / "module.py").write_text(production, encoding="utf-8")
    risk = _test_module_risk(root=tmp_path, path="tests/test_helpers.py",
                             changed_lines={1, 2, 3, 4, 5, 6, 7, 8},
                             report_paths={"module.py"},
                             changed_production_lines={"module.py": {1, 2, 3}})
    assert risk is not None and "tests/test_helpers.py:2" in risk


@pytest.mark.parametrize("production", [
    "from importlib import import_module as im\ndef price(x):\n    return im('tests.test_helpers').value(x)\n",
    "import sys\ndef price(x):\n    return sys.modules['tests.test_helpers'].value(x)\n",
])
def test_changed_production_dynamic_access_is_unknown(tmp_path: Path,
                                                       production: str) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_helpers.py").write_text(
        "def test_real():\n    assert True\n", encoding="utf-8")
    (tmp_path / "module.py").write_text(production, encoding="utf-8")
    risk = _test_module_risk(root=tmp_path, path="tests/test_helpers.py",
                             changed_lines={1, 2}, report_paths={"module.py"},
                             changed_production_lines={"module.py": {1, 2, 3}})
    assert risk is not None and "dynamic module access" in risk


def test_legitimate_added_class_test_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_helpers.py").write_text(
        "class TestHelpers:\n    def test_real(self):\n        assert True\n",
        encoding="utf-8")
    (tmp_path / "module.py").write_text("def price(x):\n    return x\n", encoding="utf-8")
    assert _test_module_risk(root=tmp_path, path="tests/test_helpers.py",
                             changed_lines={1, 2, 3}, report_paths={"module.py"},
                             changed_production_lines={"module.py": {1, 2}}) is None
