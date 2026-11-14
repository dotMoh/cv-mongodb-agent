"""The Streamlit page at least compiles and only uses agent/ functions that exist."""
import ast
import importlib
import py_compile

import pytest

from gm_helpers import ROOT

APP = ROOT / "frontend" / "app.py"


def test_app_compiles():
    if not APP.exists():
        pytest.skip("frontend/app.py not on this branch")
    py_compile.compile(str(APP), doraise=True)


def test_app_calls_real_agent_functions():
    if not APP.exists():
        pytest.skip("frontend/app.py not on this branch")
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    modules = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "agent":
            for a in node.names:
                modules[a.asname or a.name] = f"agent.{a.name}"
    missing = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in modules:
            mod = importlib.import_module(modules[node.value.id])
            if not hasattr(mod, node.attr):
                missing.append(f"{modules[node.value.id]}.{node.attr}")
    assert not missing, f"app.py calls functions agent/ doesn't have: {sorted(set(missing))}"


def test_app_renders_without_exceptions():
    if not APP.exists():
        pytest.skip("frontend/app.py not on this branch")
    pytest.importorskip("streamlit")
    pytest.importorskip("plotly")
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
