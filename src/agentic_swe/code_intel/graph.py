from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class SymbolNode:
    name: str
    kind: str  # module | class | function
    path: str
    lineno: int = 1
    docstring: str | None = None


@dataclass
class DependencyGraph:
    symbols: dict[str, SymbolNode] = field(default_factory=dict)
    imports: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # module_path -> imported module names
    files: set[str] = field(default_factory=set)

    def add_symbol(self, node: SymbolNode) -> None:
        key = f"{node.path}::{node.name}"
        self.symbols[key] = node
        self.files.add(node.path)

    def add_import(self, from_path: str, imported: str) -> None:
        self.imports[from_path].add(imported)
        self.files.add(from_path)

    def find_by_name(self, name: str) -> list[SymbolNode]:
        needle = name.lower()
        return [s for s in self.symbols.values() if needle in s.name.lower()]

    def find_files_for_keywords(self, keywords: Iterable[str]) -> list[str]:
        keys = [k.lower() for k in keywords if k]
        hits: set[str] = set()
        for symbol in self.symbols.values():
            blob = f"{symbol.name} {symbol.path} {symbol.docstring or ''}".lower()
            if any(k in blob for k in keys):
                hits.add(symbol.path)
        for path, imported in self.imports.items():
            blob = f"{path} {' '.join(imported)}".lower()
            if any(k in blob for k in keys):
                hits.add(path)
        return sorted(hits)

    def importers_of(self, module_hint: str) -> list[str]:
        hint = module_hint.lower()
        return sorted(
            path
            for path, imported in self.imports.items()
            if any(hint in item.lower() for item in imported)
        )

    def summary(self) -> dict:
        return {
            "file_count": len(self.files),
            "symbol_count": len(self.symbols),
            "import_edge_count": sum(len(v) for v in self.imports.values()),
            "top_files": sorted(self.files)[:20],
        }
