from __future__ import annotations

import ast
from pathlib import Path

from .graph import DependencyGraph, SymbolNode

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}


def index_python_repo(repo_path: Path) -> DependencyGraph:
    """Build a lightweight symbol + import dependency graph from Python sources."""
    root = repo_path.resolve()
    graph = DependencyGraph()
    _index_python_into(root, graph)
    return graph


def index_repo(repo_path: Path) -> DependencyGraph:
    """Index Python and TypeScript/JavaScript sources into one dependency graph."""
    from .typescript import index_typescript_sources

    root = repo_path.resolve()
    graph = DependencyGraph()
    _index_python_into(root, graph)
    index_typescript_sources(root, graph)
    return graph


def _index_python_into(root: Path, graph: DependencyGraph) -> None:
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = str(path.relative_to(root))
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        module_doc = ast.get_docstring(tree)
        graph.add_symbol(
            SymbolNode(
                name=path.stem,
                kind="module",
                path=rel,
                lineno=1,
                docstring=module_doc,
            )
        )

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                _record_import(graph, rel, node)
            elif isinstance(node, ast.ClassDef):
                graph.add_symbol(
                    SymbolNode(
                        name=node.name,
                        kind="class",
                        path=rel,
                        lineno=node.lineno,
                        docstring=ast.get_docstring(node),
                    )
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                graph.add_symbol(
                    SymbolNode(
                        name=node.name,
                        kind="function",
                        path=rel,
                        lineno=node.lineno,
                        docstring=ast.get_docstring(node),
                    )
                )



def _record_import(
    graph: DependencyGraph,
    path: str,
    node: ast.Import | ast.ImportFrom,
) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            graph.add_import(path, alias.name)
        return
    module = node.module or ""
    if module:
        graph.add_import(path, module)
    for alias in node.names:
        name = f"{module}.{alias.name}" if module else alias.name
        graph.add_import(path, name)
