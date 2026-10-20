"""Contracts every MCP tool must keep, checked on every pull request.

These encode rules reviewers otherwise enforce by hand:

- every registered tool has a handler and is annotated read-only;
- tool descriptions and schemas, which are sent to the model in every session,
  stay within a budget, so growth is a deliberate, visible change;
- list-returning tools default to a small number of results, and reject a
  limit outside 1..maximum with one clear message;
- the full-database smoke runner has a case for every tool;
- requirements.txt, which the Docker image installs, matches uv.lock.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import study_bible_mcp.server as server
from study_bible_mcp.database import StudyBibleDB, create_schema
from study_bible_mcp.tools import TOOLS

ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = ROOT / "src" / "study_bible_mcp" / "server.py"

# Characters of description plus JSON input schema, summed over every tool. The
# whole list rides along with every request, so raising this is a deliberate
# trade-off to make visible in review, not a number to bump in passing.
# Raised from 41,000 for the 'offset' argument of the five paged list tools.
TOOL_LIST_BUDGET = 41_500
# No single tool may grow past this (get_cross_references is the largest).
PER_TOOL_BUDGET = 7_500

# List-returning tools default to at most this many results.
DEFAULT_LIMIT_CAP = 4


def _tool_size(tool) -> int:
    return len(tool.description or "") + len(json.dumps(tool.inputSchema))


def test_every_tool_has_a_handler_and_every_handler_a_tool():
    assert {tool.name for tool in TOOLS} == set(server._TOOL_HANDLERS)


def test_every_tool_is_annotated_read_only():
    for tool in TOOLS:
        annotations = tool.annotations
        assert annotations is not None, tool.name
        assert annotations.readOnlyHint is True, tool.name
        assert annotations.destructiveHint is False, tool.name


def test_tool_list_fits_the_context_budget():
    sizes = sorted(((_tool_size(tool), tool.name) for tool in TOOLS), reverse=True)
    total = sum(size for size, _ in sizes)
    largest = ", ".join(f"{name} {size}" for size, name in sizes[:5])
    assert total <= TOOL_LIST_BUDGET, (
        f"Tool descriptions and schemas total {total} characters, over the "
        f"{TOOL_LIST_BUDGET} budget (largest: {largest}). Shorten them, or raise "
        "TOOL_LIST_BUDGET deliberately and say why in the pull request."
    )


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.name)
def test_no_single_tool_exceeds_its_budget(tool):
    assert _tool_size(tool) <= PER_TOOL_BUDGET, (
        f"{tool.name} is {_tool_size(tool)} characters (budget {PER_TOOL_BUDGET})."
    )


# Calls a handler may wrap around ``args.get("limit", N)``.
_LIMIT_WRAPPERS = {"int", "bounded_limit"}


def _limit_default(expr: ast.expr, handler: str):
    """The default a handler assigns to ``limit`` when the caller omits it."""
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id in _LIMIT_WRAPPERS
    ):
        return _limit_default(expr.args[0], handler)
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "get"
        and expr.args
        and isinstance(expr.args[0], ast.Constant)
        and expr.args[0].value == "limit"
        and len(expr.args) == 2
    ):
        return _value(expr.args[1], handler)
    if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or):
        return _value(expr.values[-1], handler)
    if isinstance(expr, ast.IfExp):
        return _value(expr.orelse, handler)
    return None


def _value(expr: ast.expr, handler: str):
    if isinstance(expr, ast.Constant):
        return expr.value
    if isinstance(expr, ast.Name):
        return getattr(server, expr.id)
    raise AssertionError(f"{handler}: cannot read the limit default from {ast.dump(expr)}")


def _handler_limit_defaults() -> dict[str, int]:
    """Map tool name -> default ``limit``, read from each handler's source."""
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
    }
    defaults = {}
    for tool_name, handler in server._TOOL_HANDLERS.items():
        function = functions[handler.__name__]
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "limit"
            ):
                default = _limit_default(node.value, handler.__name__)
                if default is not None:
                    defaults[tool_name] = default
                    break
    return defaults


def test_list_tools_default_to_a_small_number_of_results():
    defaults = _handler_limit_defaults()
    schema_limits = {
        tool.name for tool in TOOLS if "limit" in (tool.inputSchema or {}).get("properties", {})
    }
    assert schema_limits <= set(defaults), (
        f"Tools with a 'limit' argument whose default the handler does not set "
        f"recognisably: {sorted(schema_limits - set(defaults))}"
    )
    for name, default in sorted(defaults.items()):
        assert default <= DEFAULT_LIMIT_CAP, (
            f"{name} defaults to {default} results. List tools default to at most "
            f"{DEFAULT_LIMIT_CAP} so outputs stay small."
        )


def _handler_limit_maxima() -> dict[str, int]:
    """Map tool name -> the maximum its handler passes to ``bounded_limit``."""
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
    }
    maxima = {}
    for tool_name, handler in server._TOOL_HANDLERS.items():
        for node in ast.walk(functions[handler.__name__]):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "bounded_limit"
            ):
                maxima[tool_name] = _value(node.args[1], handler.__name__)
                break
    return maxima


# Arguments that get each list tool past its other checks to the limit check.
_LIMIT_CASE_ARGUMENTS = {
    "search_ancient_sources": {"query": "temple"},
    "lookup_ancient_source": {"citation": "Antiquities 18.116"},
    "search_lexicon": {"query": "love"},
    "get_cross_references": {"reference": "John 3:16"},
    "lookup_name": {"name": "David"},
    "search_by_strongs": {"strongs": "G26"},
    "find_similar_passages": {"reference": "John 3:16"},
    "get_ane_context": {"reference": "Genesis 1"},
    "get_theology_context": {"reference": "Psalm 82"},
    "list_research_sources": {},
}


def test_every_list_tool_validates_its_limit_with_bounded_limit():
    schema_limits = {
        tool.name for tool in TOOLS if "limit" in (tool.inputSchema or {}).get("properties", {})
    }
    maxima = _handler_limit_maxima()
    assert schema_limits == set(maxima), (
        "Every tool with a 'limit' argument validates it with bounded_limit: "
        f"missing {sorted(schema_limits - set(maxima))}"
    )
    assert schema_limits == set(_LIMIT_CASE_ARGUMENTS)
    defaults = _handler_limit_defaults()
    for name, maximum in maxima.items():
        assert 1 <= defaults[name] <= maximum, name
        # A bad limit is returned as text even when the handler is called directly.
        assert hasattr(server._TOOL_HANDLERS[name], "__wrapped__"), (
            f"{name}'s handler needs @returns_input_errors"
        )


@pytest.fixture
async def empty_server_db(tmp_path, monkeypatch):
    """An empty-schema database installed as the server's database."""
    path = tmp_path / "empty.db"
    conn = sqlite3.connect(path)
    create_schema(conn)
    conn.close()
    database = StudyBibleDB(path)
    await database.connect()
    monkeypatch.setattr(server, "db", database)
    yield database
    await database.close()


@pytest.mark.parametrize("tool_name", sorted(_LIMIT_CASE_ARGUMENTS))
@pytest.mark.parametrize("bad", [0, -1, "many", 2.5, True, None, "maximum+1"])
async def test_list_tools_reject_an_out_of_range_limit(empty_server_db, tool_name, bad):
    maximum = _handler_limit_maxima()[tool_name]
    limit = maximum + 1 if bad == "maximum+1" else bad
    response = await server.call_tool(tool_name, {**_LIMIT_CASE_ARGUMENTS[tool_name], "limit": limit})
    assert [item.text for item in response] == [f"'limit' must be an integer from 1 to {maximum}."]


@pytest.mark.parametrize("tool_name", sorted(_LIMIT_CASE_ARGUMENTS))
async def test_list_tools_accept_their_maximum_limit(empty_server_db, tool_name):
    maximum = _handler_limit_maxima()[tool_name]
    response = await server.call_tool(tool_name, {**_LIMIT_CASE_ARGUMENTS[tool_name], "limit": maximum})
    assert "'limit' must be" not in response[0].text
    assert not response[0].text.startswith("Error:"), response[0].text


def test_smoke_runner_has_a_case_for_every_tool():
    spec = importlib.util.spec_from_file_location(
        "smoke_server_contract", ROOT / "scripts" / "smoke_server.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    covered = set(module.TOOL_CASES) | set(getattr(module, "_PER_CORPUS_TOOLS", ()))
    assert covered == {tool.name for tool in TOOLS}


def _tracked_json_files() -> list[Path]:
    try:
        listing = subprocess.run(
            ["git", "ls-files", "*.json"], cwd=ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is unavailable, so tracked data files cannot be listed")
    return [ROOT / line for line in listing.stdout.splitlines() if line]


def test_every_tracked_json_file_parses():
    failures = []
    for path in _tracked_json_files():
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            failures.append(f"{path.relative_to(ROOT)}: {error}")
    assert not failures, "Unparseable JSON:\n" + "\n".join(failures)


# The Docker image installs requirements.txt, exported from uv.lock by this command.
REQUIREMENTS_EXPORT = "uv export --frozen --no-dev --extra sse --no-emit-project"


def _requirement_lines(text: str) -> list[str]:
    # Comments (the generated header and "# via" annotations) are not compared.
    lines = (line.strip() for line in text.splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def test_requirements_txt_matches_the_lock():
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        pytest.skip("uv is unavailable, so the lock cannot be exported")
    export = subprocess.run(
        [uv, *REQUIREMENTS_EXPORT.split()[1:], "--offline"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert export.returncode == 0, export.stderr
    committed = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert _requirement_lines(committed) == _requirement_lines(export.stdout), (
        "requirements.txt differs from uv.lock. After changing dependencies in "
        f"pyproject.toml, run `uv lock`, then `{REQUIREMENTS_EXPORT} -o requirements.txt`."
    )
