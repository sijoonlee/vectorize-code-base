from pathlib import Path

from codebase_search.extractor import extract_file


FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "sample_repo"


def _edge_keys(result: dict) -> set[tuple[str, str, str]]:
    return {(edge["source"], edge["target"], edge["relation"]) for edge in result["edges"]}


def test_extractor_emits_member_of_for_typescript_method() -> None:
    result = extract_file(FIXTURE_REPO / "src" / "rates.ts", FIXTURE_REPO)

    assert (
        "rates_rateformatter_formatpercent",
        "rates_rateformatter",
        "member_of",
    ) in _edge_keys(result)


def test_extractor_emits_exports_for_javascript_exported_arrow_function() -> None:
    result = extract_file(FIXTURE_REPO / "src" / "auth.js", FIXTURE_REPO)

    assert ("src_auth_js", "auth_requireauth", "exports") in _edge_keys(result)


def test_extractor_emits_python_local_direct_calls(tmp_path) -> None:
    repo = tmp_path
    source = repo / "util.py"
    source.write_text(
        "def helper():\n"
        "    return 1\n\n"
        "def main():\n"
        "    return helper()\n",
        encoding="utf-8",
    )

    result = extract_file(source, repo)

    assert ("util_main", "util_helper", "calls") in _edge_keys(result)
    assert ("util_helper", "util_main", "referenced_by") in _edge_keys(result)
    call = next(edge for edge in result["edges"] if edge["relation"] == "calls")
    assert call["confidence"] == 0.9
    assert call["edge_source"] == "ast_direct_identifier_call"


def test_extractor_emits_resolved_import_and_imported_call_edges(tmp_path) -> None:
    repo = tmp_path
    src = repo / "src"
    src.mkdir()
    session = src / "session.ts"
    login = src / "login.ts"
    session.write_text("export function createSession() {\n  return true;\n}\n", encoding="utf-8")
    login.write_text(
        "import { createSession as makeSession } from './session';\n\n"
        "export function loginUser() {\n"
        "  return makeSession();\n"
        "}\n",
        encoding="utf-8",
    )

    result = extract_file(login, repo)

    assert ("src_login_ts", "src_session_ts", "imports") in _edge_keys(result)
    assert ("src_login_ts", "login_loginuser", "exports") in _edge_keys(result)
    assert ("login_loginuser", "session_createsession", "calls") in _edge_keys(result)
    assert ("session_createsession", "login_loginuser", "referenced_by") in _edge_keys(result)
    call = next(edge for edge in result["edges"] if edge["relation"] == "calls")
    assert call["confidence"] == 0.85
    assert call["edge_source"] == "ast_import_alias_call"
