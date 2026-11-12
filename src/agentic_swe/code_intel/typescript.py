from __future__ import annotations

import re
from pathlib import Path

from .graph import DependencyGraph, SymbolNode
from .indexer import SKIP_DIRS

TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}

_FUNC_RE = re.compile(
    r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
)
_CLASS_RE = re.compile(r"(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"
)
_IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:[^'"]*\s+from\s+)?['"]([^'"]+)['"]"""
)
_REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")


def index_typescript_sources(root: Path, graph: DependencyGraph | None = None) -> DependencyGraph:
    """Index TS/JS sources into a dependency graph (tree-sitter if available, else regex)."""
    graph = graph or DependencyGraph()
    root = root.resolve()

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TS_EXTS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = str(path.relative_to(root))
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if _try_tree_sitter(graph, rel, source):
            continue
        _regex_index(graph, rel, source, path.stem)

    return graph


def _try_tree_sitter(graph: DependencyGraph, rel: str, source: str) -> bool:
    try:
        import tree_sitter_typescript as tstypescript
        from tree_sitter import Language, Parser
    except Exception:
        return False

    try:
        language = Language(tstypescript.language_typescript())
        parser = Parser(language)
        tree = parser.parse(source.encode("utf-8"))
    except Exception:
        return False

    graph.add_symbol(SymbolNode(name=Path(rel).stem, kind="module", path=rel, lineno=1))
    root = tree.root_node
    _walk_ts_node(graph, rel, source.encode("utf-8"), root)
    return True


def _walk_ts_node(graph: DependencyGraph, rel: str, source: bytes, node) -> None:
    typ = node.type
    if typ in {"function_declaration", "method_definition", "generator_function_declaration"}:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name = source[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="ignore")
            graph.add_symbol(
                SymbolNode(
                    name=name,
                    kind="function",
                    path=rel,
                    lineno=node.start_point[0] + 1,
                )
            )
    elif typ == "class_declaration":
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name = source[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="ignore")
            graph.add_symbol(
                SymbolNode(
                    name=name,
                    kind="class",
                    path=rel,
                    lineno=node.start_point[0] + 1,
                )
            )
    elif typ == "import_statement":
        for child in node.children:
            if child.type == "string":
                raw = source[child.start_byte : child.end_byte].decode("utf-8", errors="ignore")
                graph.add_import(rel, raw.strip("'\""))

    for child in node.children:
        _walk_ts_node(graph, rel, source, child)


def _regex_index(graph: DependencyGraph, rel: str, source: str, stem: str) -> None:
    graph.add_symbol(SymbolNode(name=stem, kind="module", path=rel, lineno=1))
    for match in _FUNC_RE.finditer(source):
        graph.add_symbol(
            SymbolNode(
                name=match.group(1),
                kind="function",
                path=rel,
                lineno=source[: match.start()].count("\n") + 1,
            )
        )
    for match in _ARROW_RE.finditer(source):
        graph.add_symbol(
            SymbolNode(
                name=match.group(1),
                kind="function",
                path=rel,
                lineno=source[: match.start()].count("\n") + 1,
            )
        )
    for match in _CLASS_RE.finditer(source):
        graph.add_symbol(
            SymbolNode(
                name=match.group(1),
                kind="class",
                path=rel,
                lineno=source[: match.start()].count("\n") + 1,
            )
        )
    for match in _IMPORT_RE.finditer(source):
        graph.add_import(rel, match.group(1))
    for match in _REQUIRE_RE.finditer(source):
        graph.add_import(rel, match.group(1))
