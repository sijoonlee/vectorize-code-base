"""Tree-sitter based extractor for graph nodes and edges (py/js/ts only)."""
from __future__ import annotations

import re
from pathlib import Path

from codebase_search.chunking import _parser_for_suffix


def extract_file(path: Path, repo: Path) -> dict:
    """Return {"nodes": [...], "edges": [...]} for a source file."""
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        rel_path = path.relative_to(repo).as_posix()
    except OSError:
        return {"nodes": [], "edges": []}

    if suffix == ".py":
        return _extract(rel_path, text, ".py", repo)
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return _extract(rel_path, text, suffix, repo)
    return {"nodes": [], "edges": []}


def _make_id(*parts: str) -> str:
    combined = "_".join(p.strip("_.") for p in parts if p)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", combined)
    return cleaned.strip("_").lower()


def _add_node(
    nodes: list[dict],
    seen: set[str],
    nid: str,
    label: str,
    entity_type: str,
    file_path: str,
    source_location: str,
) -> None:
    if nid not in seen:
        seen.add(nid)
        nodes.append({
            "id": nid,
            "label": label,
            "entity_type": entity_type,
            "file_path": file_path,
            "source_location": source_location,
        })


def _edge(
    source: str,
    target: str,
    relation: str,
    confidence: float,
    edge_source: str,
    details: str = "",
) -> dict:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "confidence": confidence,
        "edge_source": edge_source,
        "details": details,
    }


def _extract(rel_path: str, text: str, suffix: str, repo: Path) -> dict:
    parser = _parser_for_suffix(suffix)
    if parser is None:
        return {"nodes": [], "edges": []}

    tree = parser.parse(text.encode())
    stem = Path(rel_path).stem
    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()
    # Function/method AST nodes paired with the symbol id that owns calls found inside.
    # // util.py
    # def helper():
    #   return 1
    # def main():
    #     return helper()
    # call_contexts would look conceptually like:
    # [
    #     (helper_function_ast_node, "util_helper"),
    #     (main_function_ast_node, "util_main"),
    # ]
    call_contexts: list[tuple[object, str]] = []

    file_id = _make_id(rel_path)
    _add_node(nodes, seen, file_id, Path(rel_path).name, "file", rel_path, "L1")

    import_edges, imported_symbols = _extract_imports(tree.root_node, rel_path, text, suffix, repo, file_id)
    edges.extend(import_edges)

    visitor = _visit_python if suffix == ".py" else _visit_js_ts
    for node in tree.root_node.named_children:
        visitor(node, file_id, stem, rel_path, nodes, edges, seen, call_contexts, parent_class=None)

    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        edges.extend(_extract_js_ts_exports(tree.root_node, file_id, stem))
    edges.extend(_extract_calls(call_contexts, nodes, imported_symbols))

    return {"nodes": nodes, "edges": _dedupe_edges(edges)}


# ── Python ────────────────────────────────────────────────────────────────────

def _visit_python(node, parent_id, stem, rel_path, nodes, edges, seen, call_contexts, parent_class):
    t = node.type
    line = node.start_point[0] + 1

    if t == "decorated_definition":
        defn = node.child_by_field_name("definition")
        if defn is not None:
            _visit_python(defn, parent_id, stem, rel_path, nodes, edges, seen, call_contexts, parent_class)
        return

    if t == "class_definition":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = name_node.text.decode()
        class_id = _make_id(stem, class_name)
        _add_node(nodes, seen, class_id, class_name, "class", rel_path, f"L{line}")
        edges.append(_edge(parent_id, class_id, "contains", 1.0, "ast_class_definition"))
        body = node.child_by_field_name("body")
        if body:
            for child in body.named_children:
                _visit_python(child, class_id, stem, rel_path, nodes, edges, seen, call_contexts, parent_class=class_name)
        return

    if t == "function_definition":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        fn_name = name_node.text.decode()
        entity_type = "method" if parent_class else "function"
        fn_id = _make_id(stem, parent_class, fn_name) if parent_class else _make_id(stem, fn_name)
        _add_node(nodes, seen, fn_id, fn_name, entity_type, rel_path, f"L{line}")
        edges.append(_edge(parent_id, fn_id, "contains", 1.0, "ast_function_definition"))
        call_contexts.append((node, fn_id))
        if parent_class:
            edges.append(_edge(fn_id, parent_id, "member_of", 1.0, "ast_method_definition"))


# ── JavaScript / TypeScript ───────────────────────────────────────────────────

def _visit_js_ts(node, parent_id, stem, rel_path, nodes, edges, seen, call_contexts, parent_class):
    t = node.type
    line = node.start_point[0] + 1

    if t == "export_statement":
        decl = node.child_by_field_name("declaration")
        if decl is not None:
            _visit_js_ts(decl, parent_id, stem, rel_path, nodes, edges, seen, call_contexts, parent_class)
        return

    if t in {"class_declaration", "class"}:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = name_node.text.decode()
        class_id = _make_id(stem, class_name)
        _add_node(nodes, seen, class_id, class_name, "class", rel_path, f"L{line}")
        edges.append(_edge(parent_id, class_id, "contains", 1.0, "ast_class_declaration"))
        body = node.child_by_field_name("body")
        if body:
            for child in body.named_children:
                _visit_js_ts(child, class_id, stem, rel_path, nodes, edges, seen, call_contexts, parent_class=class_name)
        return

    if t in {"function_declaration", "generator_function_declaration"}:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        fn_name = name_node.text.decode()
        entity_type = "method" if parent_class else "function"
        fn_id = _make_id(stem, parent_class, fn_name) if parent_class else _make_id(stem, fn_name)
        _add_node(nodes, seen, fn_id, fn_name, entity_type, rel_path, f"L{line}")
        edges.append(_edge(parent_id, fn_id, "contains", 1.0, "ast_function_declaration"))
        call_contexts.append((node, fn_id))
        if parent_class:
            edges.append(_edge(fn_id, parent_id, "member_of", 1.0, "ast_method_definition"))
        return

    if t == "method_definition":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        fn_name = name_node.text.decode()
        fn_id = _make_id(stem, parent_class, fn_name) if parent_class else _make_id(stem, fn_name)
        _add_node(nodes, seen, fn_id, fn_name, "method", rel_path, f"L{line}")
        edges.append(_edge(parent_id, fn_id, "contains", 1.0, "ast_method_definition"))
        call_contexts.append((node, fn_id))
        if parent_class:
            edges.append(_edge(fn_id, parent_id, "member_of", 1.0, "ast_method_definition"))
        return

    if t == "lexical_declaration":
        for child in node.named_children:
            if child.type != "variable_declarator":
                continue
            value = child.child_by_field_name("value")
            if value is None or value.type not in {"arrow_function", "function", "function_expression"}:
                continue
            name_node = child.child_by_field_name("name")
            if name_node is None:
                continue
            fn_name = name_node.text.decode()
            fn_id = _make_id(stem, fn_name)
            _add_node(nodes, seen, fn_id, fn_name, "function", rel_path, f"L{line}")
            edges.append(_edge(parent_id, fn_id, "contains", 1.0, "ast_variable_function"))
            call_contexts.append((child, fn_id))


def _extract_imports(root, rel_path: str, text: str, suffix: str, repo: Path, file_id: str) -> tuple[list[dict], dict[str, str]]:
    if suffix == ".py":
        return _extract_python_imports(text, rel_path, repo, file_id)
    return _extract_js_ts_imports(text, rel_path, repo, file_id)


def _extract_js_ts_imports(text: str, rel_path: str, repo: Path, file_id: str) -> tuple[list[dict], dict[str, str]]:
    edges: list[dict] = []
    imported_symbols: dict[str, str] = {}

    for match in re.finditer(r"import\s+(?:type\s+)?(?P<body>.*?)\s+from\s+['\"](?P<spec>[^'\"]+)['\"]", text):
        spec = match.group("spec")
        target_rel = _resolve_import_path(rel_path, spec, repo)
        if target_rel is None:
            continue
        edges.append(_edge(file_id, _make_id(target_rel), "imports", 1.0, "ast_import_resolved_file", spec))
        for imported_name, local_name in _parse_js_named_imports(match.group("body")):
            imported_symbols[local_name] = _make_id(Path(target_rel).stem, imported_name)

    for match in re.finditer(r"import\s+['\"](?P<spec>[^'\"]+)['\"]", text):
        spec = match.group("spec")
        target_rel = _resolve_import_path(rel_path, spec, repo)
        if target_rel is not None:
            edges.append(_edge(file_id, _make_id(target_rel), "imports", 1.0, "ast_import_resolved_file", spec))

    return edges, imported_symbols


def _parse_js_named_imports(import_body: str) -> list[tuple[str, str]]:
    named = re.search(r"{(?P<names>[^}]+)}", import_body, flags=re.S)
    if not named:
        return []
    imports: list[tuple[str, str]] = []
    for part in named.group("names").split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        pieces = re.split(r"\s+as\s+", cleaned)
        imported_name = pieces[0].strip()
        local_name = pieces[-1].strip()
        if imported_name:
            imports.append((imported_name, local_name))
    return imports


def _extract_python_imports(text: str, rel_path: str, repo: Path, file_id: str) -> tuple[list[dict], dict[str, str]]:
    edges: list[dict] = []
    imported_symbols: dict[str, str] = {}

    pattern = re.compile(r"^\s*from\s+(?P<module>[.\w]+)\s+import\s+(?P<names>[^#\n]+)", re.M)
    for match in pattern.finditer(text):
        module = match.group("module")
        target_rel = _resolve_python_import_path(rel_path, module, repo)
        if target_rel is None:
            continue
        edges.append(_edge(file_id, _make_id(target_rel), "imports", 1.0, "ast_import_resolved_file", module))
        for imported_name, local_name in _parse_python_import_names(match.group("names")):
            imported_symbols[local_name] = _make_id(Path(target_rel).stem, imported_name)

    return edges, imported_symbols


def _parse_python_import_names(names: str) -> list[tuple[str, str]]:
    imports: list[tuple[str, str]] = []
    for part in names.strip("() ").split(","):
        cleaned = part.strip()
        if not cleaned or cleaned == "*":
            continue
        pieces = re.split(r"\s+as\s+", cleaned)
        imported_name = pieces[0].strip()
        local_name = pieces[-1].strip()
        if imported_name:
            imports.append((imported_name, local_name))
    return imports


def _resolve_import_path(rel_path: str, spec: str, repo: Path) -> str | None:
    if not spec.startswith("."):
        return None
    current_dir = repo / Path(rel_path).parent
    candidate = (current_dir / spec).resolve()
    return _resolve_source_candidate(candidate, repo)


def _resolve_python_import_path(rel_path: str, module: str, repo: Path) -> str | None:
    if module.startswith("."):
        level = len(module) - len(module.lstrip("."))
        module_tail = module[level:]
        base = repo / Path(rel_path).parent
        for _ in range(max(level - 1, 0)):
            base = base.parent
        candidate = base / module_tail.replace(".", "/")
    else:
        candidate = repo / module.replace(".", "/")
    return _resolve_source_candidate(candidate.resolve(), repo)


def _resolve_source_candidate(candidate: Path, repo: Path) -> str | None:
    candidates = [candidate]
    if candidate.suffix:
        candidates = [candidate]
    else:
        candidates = [candidate.with_suffix(ext) for ext in (".py", ".ts", ".tsx", ".js", ".jsx")]
        candidates.extend(candidate / f"index{ext}" for ext in (".ts", ".tsx", ".js", ".jsx", ".py"))

    for path in candidates:
        if path.is_file():
            try:
                return path.relative_to(repo).as_posix()
            except ValueError:
                return None
    return None


def _extract_js_ts_exports(root, file_id: str, stem: str) -> list[dict]:
    edges: list[dict] = []
    for node in root.named_children:
        if node.type != "export_statement":
            continue
        decl = node.child_by_field_name("declaration")
        if decl is None:
            continue
        for symbol_id in _symbol_ids_for_js_ts_declaration(decl, stem):
            edges.append(_edge(file_id, symbol_id, "exports", 1.0, "ast_export_statement"))
    return edges


def _symbol_ids_for_js_ts_declaration(node, stem: str) -> list[str]:
    if node.type in {"class_declaration", "class", "function_declaration", "generator_function_declaration"}:
        name_node = node.child_by_field_name("name")
        return [_make_id(stem, name_node.text.decode())] if name_node is not None else []

    if node.type == "lexical_declaration":
        ids = []
        for child in node.named_children:
            if child.type != "variable_declarator":
                continue
            value = child.child_by_field_name("value")
            if value is None or value.type not in {"arrow_function", "function", "function_expression"}:
                continue
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                ids.append(_make_id(stem, name_node.text.decode()))
        return ids

    return []


def _extract_calls(call_contexts: list[tuple[object, str]], nodes: list[dict], imported_symbols: dict[str, str]) -> list[dict]:
    name_to_ids: dict[str, set[str]] = {}
    for node in nodes:
        if node["entity_type"] == "file":
            continue
        name_to_ids.setdefault(node["label"], set()).add(node["id"])

    local_symbols = {name: next(iter(ids)) for name, ids in name_to_ids.items() if len(ids) == 1}
    edges: list[dict] = []

    for scope_node, caller_id in call_contexts:
        for call_name in _direct_call_names(scope_node):
            target_id = local_symbols.get(call_name)
            confidence = 0.9
            source = "ast_direct_identifier_call"
            if target_id is None:
                target_id = imported_symbols.get(call_name)
                confidence = 0.85
                source = "ast_import_alias_call"
            if target_id is None or target_id == caller_id:
                continue
            edges.append(_edge(caller_id, target_id, "calls", confidence, source, call_name))
            edges.append(_edge(target_id, caller_id, "referenced_by", confidence, source, call_name))

    return edges


def _direct_call_names(node) -> list[str]:
    names: list[str] = []
    for child in _walk_named(node):
        if child.type not in {"call", "call_expression"}:
            continue
        fn = child.child_by_field_name("function")
        if fn is not None and fn.type == "identifier":
            names.append(fn.text.decode())
    return names


def _walk_named(node):
    for child in node.named_children:
        yield child
        yield from _walk_named(child)


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[dict] = []
    for edge in edges:
        key = (
            edge["source"],
            edge["target"],
            edge["relation"],
            edge.get("edge_source", ""),
            edge.get("details", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped
