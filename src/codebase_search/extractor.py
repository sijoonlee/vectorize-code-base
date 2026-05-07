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
        return _extract(rel_path, text, ".py")
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return _extract(rel_path, text, suffix)
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


def _extract(rel_path: str, text: str, suffix: str) -> dict:
    parser = _parser_for_suffix(suffix)
    if parser is None:
        return {"nodes": [], "edges": []}

    tree = parser.parse(text.encode())
    stem = Path(rel_path).stem
    nodes: list[dict] = []
    edges: list[dict] = []
    seen: set[str] = set()

    file_id = _make_id(rel_path)
    _add_node(nodes, seen, file_id, Path(rel_path).name, "file", rel_path, "L1")

    visitor = _visit_python if suffix == ".py" else _visit_js_ts
    for node in tree.root_node.named_children:
        visitor(node, file_id, stem, rel_path, nodes, edges, seen, parent_class=None)

    return {"nodes": nodes, "edges": edges}


# ── Python ────────────────────────────────────────────────────────────────────

def _visit_python(node, parent_id, stem, rel_path, nodes, edges, seen, parent_class):
    t = node.type
    line = node.start_point[0] + 1

    if t == "decorated_definition":
        defn = node.child_by_field_name("definition")
        if defn is not None:
            _visit_python(defn, parent_id, stem, rel_path, nodes, edges, seen, parent_class)
        return

    if t == "class_definition":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = name_node.text.decode()
        class_id = _make_id(stem, class_name)
        _add_node(nodes, seen, class_id, class_name, "class", rel_path, f"L{line}")
        edges.append({"source": parent_id, "target": class_id, "relation": "contains"})
        body = node.child_by_field_name("body")
        if body:
            for child in body.named_children:
                _visit_python(child, class_id, stem, rel_path, nodes, edges, seen, parent_class=class_name)
        return

    if t == "function_definition":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        fn_name = name_node.text.decode()
        entity_type = "method" if parent_class else "function"
        fn_id = _make_id(stem, parent_class, fn_name) if parent_class else _make_id(stem, fn_name)
        _add_node(nodes, seen, fn_id, fn_name, entity_type, rel_path, f"L{line}")
        edges.append({"source": parent_id, "target": fn_id, "relation": "contains"})


# ── JavaScript / TypeScript ───────────────────────────────────────────────────

def _visit_js_ts(node, parent_id, stem, rel_path, nodes, edges, seen, parent_class):
    t = node.type
    line = node.start_point[0] + 1

    if t == "export_statement":
        decl = node.child_by_field_name("declaration")
        if decl is not None:
            _visit_js_ts(decl, parent_id, stem, rel_path, nodes, edges, seen, parent_class)
        return

    if t in {"class_declaration", "class"}:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = name_node.text.decode()
        class_id = _make_id(stem, class_name)
        _add_node(nodes, seen, class_id, class_name, "class", rel_path, f"L{line}")
        edges.append({"source": parent_id, "target": class_id, "relation": "contains"})
        body = node.child_by_field_name("body")
        if body:
            for child in body.named_children:
                _visit_js_ts(child, class_id, stem, rel_path, nodes, edges, seen, parent_class=class_name)
        return

    if t in {"function_declaration", "generator_function_declaration"}:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        fn_name = name_node.text.decode()
        entity_type = "method" if parent_class else "function"
        fn_id = _make_id(stem, parent_class, fn_name) if parent_class else _make_id(stem, fn_name)
        _add_node(nodes, seen, fn_id, fn_name, entity_type, rel_path, f"L{line}")
        edges.append({"source": parent_id, "target": fn_id, "relation": "contains"})
        return

    if t == "method_definition":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        fn_name = name_node.text.decode()
        fn_id = _make_id(stem, parent_class, fn_name) if parent_class else _make_id(stem, fn_name)
        _add_node(nodes, seen, fn_id, fn_name, "method", rel_path, f"L{line}")
        edges.append({"source": parent_id, "target": fn_id, "relation": "contains"})
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
            edges.append({"source": parent_id, "target": fn_id, "relation": "contains"})
