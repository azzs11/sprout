"""Tests for tree-sitter symbol extraction and hunk-to-symbol mapping."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sprout.core.code.languages import supported_languages
from sprout.core.code.symbols import definitions, symbols_for_lines

CASES: dict[str, tuple[bytes, list[str]]] = {
    "a.py": (
        b"class A:\n    def m(self):\n        pass\n\n@dec\ndef f():\n    pass\n",
        ["A", "A.m", "f"],
    ),
    "a.js": (
        b"function f() {}\nclass K { m() {} }\nconst g = () => 1;\nconst x = 5;\n",
        ["f", "K", "K.m", "g"],
    ),
    "a.ts": (
        b"interface I { a: number }\nexport class C { run(): void {} }\n",
        ["I", "C", "C.run"],
    ),
    "a.tsx": (b"export const App = () => <div/>;\n", ["App"]),
    "a.go": (b"package p\ntype S struct{}\nfunc (s *S) M() {}\nfunc F() {}\n", ["S", "M", "F"]),
    "a.rs": (b"struct S;\nimpl S { fn m(&self) {} }\nfn f() {}\n", ["S", "S", "S.m", "f"]),
    "A.java": (b"class A { A() {} void m() {} }\n", ["A", "A.A", "A.m"]),
    "a.c": (
        b"struct s { int a; };\nint f(int x) { return x; }\nstatic char *g(void) { return 0; }\n",
        ["s", "f", "g"],
    ),
    "a.cpp": (b"namespace n { class C { }; }\nint main() { return 0; }\n", ["n", "n.C", "main"]),
    "a.rb": (b"module M\n  class C\n    def m; end\n  end\nend\n", ["M", "M.C", "M.C.m"]),
    "a.cs": (b"namespace N { class C { void M() {} } }\n", ["N", "N.C", "N.C.M"]),
    "a.php": (b"<?php\nclass C { function m() {} }\nfunction f() {}\n", ["C", "C.m", "f"]),
    "a.kt": (b"class C { fun m() {} }\nfun f() {}\n", ["C", "C.m", "f"]),
}


@pytest.mark.parametrize("path", sorted(CASES))
def test_definitions_per_language(path: str) -> None:
    source, expected = CASES[path]
    assert [d.name for d in definitions(path, source)] == expected


def test_every_bundled_language_has_a_case() -> None:
    from sprout.core.code.languages import spec_for_path

    covered = {spec.name for p in CASES if (spec := spec_for_path(p)) is not None}
    assert covered == set(supported_languages())


def test_unsupported_and_empty_files() -> None:
    assert definitions("notes.txt", b"def f(): pass") == []
    assert definitions("a.py", b"") == []


PY = b"""class Payments:
    retries = 3

    def charge(self):
        return 1

    def refund(self):
        return 2


def helper():
    return 3
"""
DEFS = definitions("p.py", PY)


@pytest.mark.parametrize(
    ("start", "count", "expected"),
    [
        (5, 1, ["Payments.charge"]),  # body of charge
        (2, 1, ["Payments"]),  # class attribute, not inside a method
        (5, 4, ["Payments.charge", "Payments.refund"]),  # hunk spans two methods
        (12, 1, ["helper"]),
        (8, 0, ["Payments.refund"]),  # pure insertion right after refund's last line
        (10, 0, []),  # insertion between top-level definitions
    ],
)
def test_symbols_for_lines(start: int, count: int, expected: list[str]) -> None:
    assert symbols_for_lines(DEFS, start, count) == expected


@given(st.binary(max_size=2_000))
def test_random_bytes_never_crash_parser(source: bytes) -> None:
    for path in ("x.py", "x.ts", "x.c", "x.rb"):
        defs = definitions(path, source)
        assert all(d.start <= d.end for d in defs)
