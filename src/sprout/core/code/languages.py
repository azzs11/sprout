"""Bundled tree-sitter grammars and the node types that define symbols in each.

Grammars ship as wheels, so parsing works offline and nothing is downloaded at runtime.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import cache
from pathlib import PurePosixPath

from tree_sitter import Language


@dataclass(frozen=True)
class LanguageSpec:
    """How to load one grammar and which nodes count as named definitions."""

    name: str
    module: str
    function: str
    definitions: frozenset[str]


def _spec(name: str, module: str, definitions: str, function: str = "language") -> LanguageSpec:
    return LanguageSpec(name, module, function, frozenset(definitions.split()))


_JS_DEFS = (
    "function_declaration generator_function_declaration method_definition class_declaration "
    "variable_declarator"
)
_TS_DEFS = (
    _JS_DEFS + " abstract_class_declaration interface_declaration enum_declaration "
    "type_alias_declaration function_signature abstract_method_signature"
)

_SPECS: tuple[LanguageSpec, ...] = (
    _spec("python", "tree_sitter_python", "function_definition class_definition"),
    _spec("javascript", "tree_sitter_javascript", _JS_DEFS),
    _spec("typescript", "tree_sitter_typescript", _TS_DEFS, "language_typescript"),
    _spec("tsx", "tree_sitter_typescript", _TS_DEFS, "language_tsx"),
    _spec("go", "tree_sitter_go", "function_declaration method_declaration type_spec"),
    _spec(
        "rust",
        "tree_sitter_rust",
        "function_item impl_item struct_item enum_item trait_item mod_item macro_definition",
    ),
    _spec(
        "java",
        "tree_sitter_java",
        "class_declaration interface_declaration enum_declaration record_declaration "
        "method_declaration constructor_declaration",
    ),
    _spec("c", "tree_sitter_c", "function_definition struct_specifier enum_specifier"),
    _spec(
        "cpp",
        "tree_sitter_cpp",
        "function_definition class_specifier struct_specifier namespace_definition",
    ),
    _spec("ruby", "tree_sitter_ruby", "method singleton_method class module"),
    _spec(
        "csharp",
        "tree_sitter_c_sharp",
        "class_declaration struct_declaration interface_declaration enum_declaration "
        "record_declaration method_declaration constructor_declaration namespace_declaration",
    ),
    _spec(
        "php",
        "tree_sitter_php",
        "function_definition method_declaration class_declaration interface_declaration "
        "trait_declaration",
        "language_php",
    ),
    _spec(
        "kotlin", "tree_sitter_kotlin", "function_declaration class_declaration object_declaration"
    ),
)

_BY_NAME = {spec.name: spec for spec in _SPECS}

_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".rb": "ruby",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin",
    ".kts": "kotlin",
}


def spec_for_path(path: str) -> LanguageSpec | None:
    """Return the language spec for a file path, or None if it is not supported."""
    name = _EXTENSIONS.get(PurePosixPath(path).suffix.lower())
    return _BY_NAME[name] if name else None


@cache
def load_language(spec: LanguageSpec) -> Language:
    """Load (once) the grammar for ``spec``."""
    module = importlib.import_module(spec.module)
    capsule: object = getattr(module, spec.function)()  # a PyCapsule, not the deprecated int
    return Language(capsule)


def supported_languages() -> list[str]:
    """Names of every bundled language."""
    return [spec.name for spec in _SPECS]
