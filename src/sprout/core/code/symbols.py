"""Map changed line ranges to the functions and classes that contain them."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from tree_sitter import Node, Parser

from sprout.core.code.languages import LanguageSpec, load_language, spec_for_path

MAX_PARSE_BYTES = 1_000_000
_FUNCTION_VALUES = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)
_NAME_TYPES = frozenset(
    {
        "identifier",
        "type_identifier",
        "field_identifier",
        "property_identifier",
        "simple_identifier",
        "constant",
        "name",
        "qualified_identifier",
        "destructor_name",
        "operator_name",
        "namespace_identifier",
    }
)


@dataclass(frozen=True)
class Definition:
    """A named definition and the 0-based rows it spans (inclusive)."""

    name: str
    start: int
    end: int
    depth: int


def definitions(path: str, source: bytes) -> list[Definition]:
    """Every named definition in a file, outermost first. Empty for unsupported files."""
    spec = spec_for_path(path)
    if spec is None or not source or len(source) > MAX_PARSE_BYTES:
        return []
    tree = Parser(load_language(spec)).parse(source)
    return list(_walk(tree.root_node, spec, prefix=(), depth=0))


def symbols_for_lines(defs: list[Definition], start: int, count: int) -> list[str]:
    """Innermost definitions overlapping 1-based lines ``start .. start+count-1``.

    A pure insertion (``count == 0``) is treated as touching the line it follows.
    """
    first = max(start - 1, 0)
    last = first + max(count, 1) - 1
    hits = [d for d in defs if d.start <= last and d.end >= first]
    innermost = [
        d
        for d in hits
        if not any(o.depth > d.depth and o.start >= d.start and o.end <= d.end for o in hits)
    ]
    return list(dict.fromkeys(d.name for d in innermost))


def _walk(
    node: Node, spec: LanguageSpec, prefix: tuple[str, ...], depth: int
) -> Iterator[Definition]:
    for child in node.named_children:
        name = _definition_name(child, spec)
        if name is None:
            yield from _walk(child, spec, prefix, depth)
            continue
        qualified = (*prefix, name)
        yield Definition(".".join(qualified), child.start_point.row, child.end_point.row, depth)
        yield from _walk(child, spec, qualified, depth + 1)


def _definition_name(node: Node, spec: LanguageSpec) -> str | None:
    if node.type not in spec.definitions:
        return None
    if node.type == "variable_declarator":
        value = node.child_by_field_name("value")
        if value is None or value.type not in _FUNCTION_VALUES:
            return None
    target = (
        node.child_by_field_name("name")
        or _declarator_name(node)  # C/C++ functions: the type field is the return type
        or node.child_by_field_name("type")  # Rust impl blocks
        or _first_name_child(node)
    )
    if target is None or target.text is None:
        return None
    return target.text.decode("utf-8", errors="replace")


def _declarator_name(node: Node) -> Node | None:
    """Follow C/C++ ``declarator`` fields down to the identifier."""
    current = node.child_by_field_name("declarator")
    while current is not None:
        if current.type in _NAME_TYPES:
            return current
        current = current.child_by_field_name("declarator")
    return None


def _first_name_child(node: Node) -> Node | None:
    return next((c for c in node.named_children if c.type in _NAME_TYPES), None)
