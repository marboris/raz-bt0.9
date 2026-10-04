#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import json
import re
import sys


class RazError(Exception):
    def __init__(self, message: str, line: int, column: int, source: str | None = None):
        location = f"{source}:{line}:{column}" if source else f"{line}:{column}"
        super().__init__(f"{message} at {location}")
        self.line = line
        self.column = column
        self.source = source


@dataclass(frozen=True)
class Span:
    line: int
    column: int
    source: str


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    column: int
    source: str

    @property
    def span(self) -> Span:
        return Span(self.line, self.column, self.source)


KEYWORDS = {
    "use", "include", "function", "let", "return", "if", "else", "while", "for",
    "true", "false", "macro", "async", "await", "new"
}


class Lexer:
    def __init__(self, text: str, source_name: str):
        self.text = text
        self.source_name = source_name
        self.i = 0
        self.line = 1
        self.col = 1

    def _advance(self) -> str:
        ch = self.text[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _peek(self, offset: int = 0) -> str:
        pos = self.i + offset
        return self.text[pos] if pos < len(self.text) else ""

    def tokens(self) -> list[Token]:
        out: list[Token] = []
        single = "{}();,=+-*/<>!:%[]."
        while self.i < len(self.text):
            ch = self._peek()
            if ch.isspace():
                self._advance()
                continue

            # Line comments.
            if ch == "/" and self._peek(1) == "/":
                self._advance()
                self._advance()
                while self.i < len(self.text) and self._peek() != "\n":
                    self._advance()
                continue

            # Block comments.
            if ch == "/" and self._peek(1) == "*":
                start_line, start_col = self.line, self.col
                self._advance()
                self._advance()
                closed = False
                while self.i < len(self.text):
                    if self._peek() == "*" and self._peek(1) == "/":
                        self._advance()
                        self._advance()
                        closed = True
                        break
                    self._advance()
                if not closed:
                    raise RazError("unterminated block comment", start_line, start_col, self.source_name)
                continue

            line, col = self.line, self.col

            if ch.isalpha() or ch == "_":
                value = self._advance()
                while self.i < len(self.text) and (self._peek().isalnum() or self._peek() == "_"):
                    value += self._advance()
                out.append(Token(value if value in KEYWORDS else "IDENT", value, line, col, self.source_name))
                continue

            if ch.isdigit():
                value = self._advance()
                kind = "INT"
                while self.i < len(self.text) and self._peek().isdigit():
                    value += self._advance()
                if self.i < len(self.text) and self._peek() == ".":
                    kind = "FLOAT"
                    value += self._advance()
                    if self.i >= len(self.text) or not self._peek().isdigit():
                        raise RazError("expected digits after '.'", self.line, self.col, self.source_name)
                    while self.i < len(self.text) and self._peek().isdigit():
                        value += self._advance()
                    if self.i < len(self.text) and self._peek() in ("f", "F"):
                        kind = "FLOAT32"
                        value += self._advance()
                out.append(Token(kind, value, line, col, self.source_name))
                continue

            if ch == '"':
                self._advance()
                value = ""
                closed = False
                while self.i < len(self.text):
                    if self._peek() == '"':
                        self._advance()
                        closed = True
                        break
                    if self._peek() == "\\":
                        self._advance()
                        if self.i >= len(self.text):
                            break
                        esc = self._advance()
                        value += {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(esc, esc)
                    else:
                        value += self._advance()
                if not closed:
                    raise RazError("unterminated string", line, col, self.source_name)
                out.append(Token("STRING", value, line, col, self.source_name))
                continue

            if ch == "'":
                self._advance()
                if self.i >= len(self.text):
                    raise RazError("unterminated character literal", line, col, self.source_name)
                if self._peek() == "\\":
                    self._advance()
                    if self.i >= len(self.text):
                        raise RazError("unterminated character literal", line, col, self.source_name)
                    esc = self._advance()
                    value = {"n": "\n", "t": "\t", "r": "\r", "'": "'", "\\": "\\"}.get(esc, esc)
                else:
                    value = self._advance()
                if self._peek() != "'":
                    raise RazError("character literal must contain exactly one character", line, col, self.source_name)
                self._advance()
                out.append(Token("CHAR", value, line, col, self.source_name))
                continue

            multi = None
            for candidate in ("::", "->", "<=", ">=", "==", "!=", "&&", "||"):
                if self.text.startswith(candidate, self.i):
                    multi = candidate
                    break
            if multi:
                for _ in multi:
                    self._advance()
                out.append(Token(multi, multi, line, col, self.source_name))
                continue

            if ch in single:
                out.append(Token(ch, self._advance(), line, col, self.source_name))
                continue

            raise RazError(f"unexpected character {ch!r}", line, col, self.source_name)

        out.append(Token("EOF", "", self.line, self.col, self.source_name))
        return out


@dataclass
class Node:
    span: Span


@dataclass
class Program(Node):
    statements: list[Node]


@dataclass
class Use(Node):
    name: str


@dataclass
class Include(Node):
    path: str


@dataclass
class CoreDirective(Node):
    name: str
    value: str


@dataclass
class Macro(Node):
    name: str
    params: list[str]
    body: list[Node]

    @property
    def is_expression_macro(self) -> bool:
        return len(self.body) == 1 and isinstance(self.body[0], Return) and self.body[0].expr is not None


@dataclass
class Parameter:
    name: str
    type_name: str | None
    span: Span


@dataclass
class Function(Node):
    name: str
    params: list[Parameter]
    return_type: str | None
    body: list[Node]
    is_async: bool = False


@dataclass
class Let(Node):
    name: str
    type_name: str | None
    expr: Node


@dataclass
class Assign(Node):
    name: str
    expr: Node


@dataclass
class Return(Node):
    expr: Node | None


@dataclass
class ExprStmt(Node):
    expr: Node


@dataclass
class If(Node):
    condition: Node
    then_body: list[Node]
    else_body: list[Node] | None


@dataclass
class While(Node):
    condition: Node
    body: list[Node]


@dataclass
class For(Node):
    init: Node | None
    condition: Node | None
    update: Node | None
    body: list[Node]


@dataclass
class Call(Node):
    parts: list[str]
    args: list[Node]


@dataclass
class MemberCall(Node):
    base: Node
    name: str
    args: list[Node]


@dataclass
class Member(Node):
    base: Node
    name: str


@dataclass
class Index(Node):
    base: Node
    index: Node


@dataclass
class NewExpr(Node):
    type_name: str
    args: list[Node]


@dataclass
class CollectionLiteral(Node):
    kind: str
    items: list[tuple[Node, Node | None]]


@dataclass
class Literal(Node):
    kind: str
    value: object


@dataclass
class Name(Node):
    value: str


@dataclass
class Binary(Node):
    left: Node
    op: str
    right: Node


@dataclass
class Unary(Node):
    op: str
    operand: Node


@dataclass
class Await(Node):
    expr: Node


class Parser:
    def __init__(self, tokens: list[Token]):
        self.t = tokens
        self.i = 0

    def cur(self) -> Token:
        return self.t[self.i]

    def take(self, kind: str) -> Token:
        tok = self.cur()
        if tok.kind != kind:
            raise RazError(f"expected {kind}, got {tok.kind}", tok.line, tok.column, tok.source)
        self.i += 1
        return tok

    def maybe(self, kind: str) -> bool:
        if self.cur().kind == kind:
            self.i += 1
            return True
        return False

    def parse(self) -> Program:
        statements: list[Node] = []
        start = self.cur().span
        while self.cur().kind != "EOF":
            statements.append(self.statement())
        return Program(start, statements)

    def statement(self) -> Node:
        tok = self.cur()
        if self.maybe("use"):
            name = self.take("IDENT").value
            self.take(";")
            return Use(tok.span, name)

        if self.maybe("include"):
            self.take("(")
            path = self.take("STRING").value
            self.take(")")
            self.take(";")
            return Include(tok.span, path)

        if tok.kind == "IDENT" and tok.value in {"__eval", "__phead"}:
            self.i += 1
            self.take("(")
            value = self.take("STRING").value
            self.take(")")
            self.take(";")
            return CoreDirective(tok.span, tok.value, value)

        if self.maybe("macro"):
            name_tok = self.take("IDENT")
            self.take("(")
            params: list[str] = []
            if self.cur().kind != ")":
                while True:
                    params.append(self.take("IDENT").value)
                    if not self.maybe(","):
                        break
            self.take(")")
            body = self.block()
            return Macro(tok.span, name_tok.value, params, body)

        async_flag = self.maybe("async")
        if async_flag and self.cur().kind != "function":
            tok_async = self.t[self.i - 1]
            raise RazError("async must be followed by function", tok_async.line, tok_async.column, tok_async.source)
        if self.maybe("function"):
            name_tok = self.take("IDENT")
            self.take("(")
            params: list[Parameter] = []
            if self.cur().kind != ")":
                while True:
                    param_tok = self.take("IDENT")
                    type_name = self.parse_optional_type()
                    params.append(Parameter(param_tok.value, type_name, param_tok.span))
                    if not self.maybe(","):
                        break
            self.take(")")
            return_type = None
            if self.maybe("->"):
                return_type = self.parse_type_name()
            body = self.block()
            return Function(tok.span, name_tok.value, params, return_type, body, async_flag)

        if self.maybe("let"):
            name_tok = self.take("IDENT")
            type_name = self.parse_optional_type()
            self.take("=")
            expr = self.expression()
            self.take(";")
            return Let(tok.span, name_tok.value, type_name, expr)

        if self.maybe("return"):
            if self.maybe(";"):
                return Return(tok.span, None)
            expr = self.expression()
            self.take(";")
            return Return(tok.span, expr)

        if self.maybe("if"):
            self.take("(")
            condition = self.expression()
            self.take(")")
            then_body = self.block()
            else_body: list[Node] | None = None
            if self.maybe("else"):
                if self.cur().kind == "if":
                    nested = self.statement()
                    else_body = [nested]
                else:
                    else_body = self.block()
            return If(tok.span, condition, then_body, else_body)

        if self.maybe("while"):
            self.take("(")
            condition = self.expression()
            self.take(")")
            body = self.block()
            return While(tok.span, condition, body)

        if self.maybe("for"):
            self.take("(")
            init: Node | None = None
            if self.cur().kind != ";":
                init = self.for_part(allow_let=True)
            self.take(";")
            condition: Node | None = None
            if self.cur().kind != ";":
                condition = self.expression()
            self.take(";")
            update: Node | None = None
            if self.cur().kind != ")":
                update = self.for_part(allow_let=False)
            self.take(")")
            body = self.block()
            return For(tok.span, init, condition, update, body)

        if self.cur().kind == "IDENT" and self.t[self.i + 1].kind == "=":
            name = self.take("IDENT")
            self.take("=")
            expr = self.expression()
            self.take(";")
            return Assign(name.span, name.value, expr)

        expr = self.expression()
        self.take(";")
        return ExprStmt(tok.span, expr)

    def for_part(self, *, allow_let: bool) -> Node:
        if allow_let and self.maybe("let"):
            tok = self.t[self.i - 1]
            name_tok = self.take("IDENT")
            type_name = self.parse_optional_type()
            self.take("=")
            expr = self.expression()
            return Let(tok.span, name_tok.value, type_name, expr)
        if self.cur().kind == "IDENT" and self.t[self.i + 1].kind == "=":
            name = self.take("IDENT")
            self.take("=")
            expr = self.expression()
            return Assign(name.span, name.value, expr)
        return ExprStmt(self.cur().span, self.expression())

    def parse_optional_type(self) -> str | None:
        if not self.maybe(":"):
            return None
        return self.parse_type_name()

    def parse_type_name(self) -> str:
        tok = self.cur()
        name = self.take("IDENT").value
        if self.maybe("<"):
            args = [self.parse_type_name()]
            while self.maybe(","):
                args.append(self.parse_type_name())
            self.take(">")
            name = name + "<" + ",".join(args) + ">"
        return name

    def block(self) -> list[Node]:
        self.take("{")
        out: list[Node] = []
        while self.cur().kind not in ("}", "EOF"):
            out.append(self.statement())
        self.take("}")
        return out

    def expression(self, min_prec: int = 0) -> Node:
        left = self.unary()
        precedence = {
            "||": 1,
            "&&": 2,
            "==": 3, "!=": 3,
            "<": 4, "<=": 4, ">": 4, ">=": 4,
            "+": 5, "-": 5,
            "*": 6, "/": 6,
        }
        while self.cur().kind in precedence and precedence[self.cur().kind] >= min_prec:
            op_tok = self.take(self.cur().kind)
            right = self.expression(precedence[op_tok.kind] + 1)
            left = Binary(op_tok.span, left, op_tok.value, right)
        return left

    def unary(self) -> Node:
        if self.maybe("await"):
            tok = self.t[self.i - 1]
            return Await(tok.span, self.unary())
        if self.cur().kind in ("-", "+", "!"):
            tok = self.take(self.cur().kind)
            return Unary(tok.span, tok.value, self.unary())
        return self.primary()

    def primary(self) -> Node:
        tok = self.cur()
        if self.maybe("STRING"):
            node: Node = Literal(tok.span, "string", tok.value)
        elif self.maybe("CHAR"):
            node = Literal(tok.span, "char", tok.value)
        elif self.maybe("INT"):
            node = Literal(tok.span, "int", int(tok.value))
        elif self.maybe("FLOAT"):
            node = Literal(tok.span, "float", float(tok.value))
        elif self.maybe("FLOAT32"):
            node = Literal(tok.span, "float32", float(tok.value[:-1]))
        elif self.maybe("true"):
            node = Literal(tok.span, "bool", True)
        elif self.maybe("false"):
            node = Literal(tok.span, "bool", False)
        elif self.maybe("("):
            node = self.expression()
            self.take(")")
        elif self.maybe("["):
            items: list[tuple[Node, Node | None]] = []
            if self.cur().kind != "]":
                while True:
                    value = self.expression()
                    items.append((value, None))
                    if not self.maybe(","):
                        break
            self.take("]")
            node = CollectionLiteral(tok.span, "list", items)
        elif self.maybe("{"):
            items = []
            if self.cur().kind != "}":
                while True:
                    key = self.expression()
                    self.take(":")
                    value = self.expression()
                    items.append((key, value))
                    if not self.maybe(","):
                        break
            self.take("}")
            node = CollectionLiteral(tok.span, "map", items)
        elif self.maybe("new"):
            type_name = self.parse_type_name()
            self.take("(")
            args = self.call_args()
            node = NewExpr(tok.span, type_name, args)
        else:
            first = self.take("IDENT")
            node = Name(first.span, first.value)
            if self.cur().kind == "::":
                parts = [first.value]
                while self.maybe("::"):
                    parts.append(self.take("IDENT").value)
                if self.maybe("("):
                    node = Call(first.span, parts, self.call_args())
                else:
                    raise RazError("qualified name must be a function call", self.cur().line, self.cur().column, self.cur().source)
            elif self.maybe("("):
                node = Call(first.span, [first.value], self.call_args())

        while True:
            if self.maybe("."):
                member = self.take("IDENT")
                if self.maybe("("):
                    node = MemberCall(member.span, node, member.value, self.call_args())
                else:
                    node = Member(member.span, node, member.value)
                continue
            if self.maybe("["):
                index_tok = self.cur()
                index = self.expression()
                self.take("]")
                node = Index(index_tok.span, node, index)
                continue
            break
        return node

    def call_args(self) -> list[Node]:
        args: list[Node] = []
        if self.cur().kind != ")":
            while True:
                args.append(self.expression())
                if not self.maybe(","):
                    break
        self.take(")")
        return args


def cpp_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )
    return f'std::string("{escaped}")'


class SemanticError(RazError):
    pass


@dataclass
class PackageConfig:
    root: Path
    name: str
    version: str
    stdlib: Path | None
    source_roots: tuple[Path, ...]
    dependencies: dict[str, Path]


@dataclass
class Module:
    path: Path
    program: Program
    name: str
    imports: list["Module"]
    package: PackageConfig
    package_parts: tuple[str, ...]

    @property
    def qualified_name(self) -> tuple[str, ...]:
        return self.package_parts + (self.name,) if self.package_parts else (self.name,)

    @property
    def functions(self) -> dict[str, Function]:
        return {s.name: s for s in self.program.statements if isinstance(s, Function)}

    @property
    def macros(self) -> dict[str, Macro]:
        return {s.name: s for s in self.program.statements if isinstance(s, Macro)}


class ModuleLoader:
    def __init__(self, package: PackageConfig) -> None:
        self.root_package = package
        self.cache: dict[Path, Module] = {}
        self.loading: list[Path] = []
        self.module_names: dict[tuple[str, ...], Path] = {}

    def load(self, path: Path, *, package: PackageConfig | None = None, package_parts: tuple[str, ...] | None = None) -> Module:
        path = path.resolve()
        package = package or self.root_package
        if path in self.loading:
            cycle = self.loading[self.loading.index(path):] + [path]
            joined = " -> ".join(p.name for p in cycle)
            raise SemanticError(f"cyclic include detected: {joined}", 1, 1, str(path))
        if path in self.cache:
            return self.cache[path]
        if not path.exists():
            raise RazError("source file not found", 1, 1, str(path))
        if path.suffix not in {".ro", ".rt"}:
            raise RazError("included source must use .ro or .rt", 1, 1, str(path))

        self.loading.append(path)
        try:
            text = path.read_text(encoding="utf-8")
            program = Parser(Lexer(text, str(path)).tokens()).parse()
            name = path.stem
            parts = package_parts or ()
            qualified = parts + (name,)
            previous = self.module_names.get(qualified)
            if previous is not None and previous != path:
                dotted = "::".join(qualified)
                raise RazError(
                    f"module name {dotted} is ambiguous: both {previous} and {path} use this name",
                    program.span.line,
                    program.span.column,
                    str(path),
                )
            self.module_names[qualified] = path
            module = Module(path, program, name, [], package, parts)
            self.cache[path] = module

            for stmt in program.statements:
                if isinstance(stmt, Include):
                    child_path, child_package, child_parts = self._resolve_include(stmt.path, module)
                    child = self.load(child_path, package=child_package, package_parts=child_parts)
                    if child.qualified_name in {m.qualified_name for m in module.imports}:
                        qname = "::".join(child.qualified_name)
                        raise SemanticError(
                            f"duplicate module name {qname} in include list",
                            stmt.span.line,
                            stmt.span.column,
                            stmt.span.source,
                        )
                    module.imports.append(child)
            return module
        finally:
            self.loading.pop()

    def _resolve_include(self, spec: str, importer: Module) -> tuple[Path, PackageConfig, tuple[str, ...]]:
        if spec.startswith("std:"):
            if importer.package.stdlib is None:
                raise RazError("standard library is not configured for this package", importer.program.span.line, importer.program.span.column, str(importer.path))
            rel = spec[4:].strip("/")
            path = self._with_source_extension(importer.package.stdlib / rel)
            return path, importer.package, ("std",)

        if spec.startswith("pkg:"):
            raw = spec[4:].strip("/")
            if "/" not in raw:
                raise RazError("package include must use pkg:name/module", importer.program.span.line, importer.program.span.column, str(importer.path))
            dep_name, rel = raw.split("/", 1)
            dep_root = importer.package.dependencies.get(dep_name)
            if dep_root is None:
                raise RazError(f"unknown package dependency {dep_name}", importer.program.span.line, importer.program.span.column, str(importer.path))
            dep_package = self._load_package(dep_root, expected_name=dep_name)
            path = self._resolve_from_source_roots(dep_package, rel)
            return path, dep_package, (dep_package.name,)

        if spec.startswith("src:"):
            rel = spec[4:].strip("/")
            path = self._resolve_from_source_roots(importer.package, rel)
            return path, importer.package, importer.package_parts

        path = self._with_source_extension(importer.path.parent / spec)
        return path.resolve(), importer.package, importer.package_parts

    @staticmethod
    def _with_source_extension(path: Path) -> Path:
        if path.suffix in {".ro", ".rt"}:
            return path.resolve()
        return path.with_suffix(".ro").resolve()

    @classmethod
    def _resolve_from_source_roots(cls, package: PackageConfig, rel: str) -> Path:
        candidates: list[Path] = []
        for source_root in package.source_roots:
            candidates.append(cls._with_source_extension(source_root / rel))
        candidates.append(cls._with_source_extension(package.root / rel))
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _load_package(self, root: Path, *, expected_name: str) -> PackageConfig:
        manifest = root / "raz.json" if root.is_dir() else root
        config = load_package_config(manifest)
        if config.name != expected_name:
            raise RazError(
                f"package dependency {expected_name} resolves to package {config.name}",
                1,
                1,
                str(manifest),
            )
        return config


class MacroExpander:
    """Small AST-level macro system for M0.4.

    A macro is intentionally constrained so expansion stays predictable during bootstrap:
      - expression macro: exactly `return <expr>;`
      - statement macro: only expression statements and Core directives
    Macro definitions never reach code generation.
    """

    def __init__(self, root: Module):
        self.root = root
        self.registry: dict[Path, dict[str, Macro]] = {}

    def expand(self) -> None:
        modules = self._all_modules(self.root)
        self.registry = {module.path: dict(module.macros) for module in modules}
        for module in modules:
            self._validate_definitions(module)
        for module in modules:
            module.program.statements = self._expand_statements(module.program.statements, module, [], top_level=True)

    def _all_modules(self, root: Module) -> list[Module]:
        out: list[Module] = []
        seen: set[Path] = set()

        def visit(module: Module) -> None:
            if module.path in seen:
                return
            seen.add(module.path)
            for child in module.imports:
                visit(child)
            out.append(module)

        visit(root)
        return out

    def _validate_definitions(self, module: Module) -> None:
        functions = module.functions
        macros = module.macros
        overlap = set(functions) & set(macros)
        if overlap:
            name = sorted(overlap)[0]
            node = macros[name]
            raise SemanticError(
                f"name {name} is declared as both function and macro",
                node.span.line,
                node.span.column,
                node.span.source,
            )
        seen: set[str] = set()
        for macro in macros.values():
            if macro.name in seen:
                raise SemanticError(
                    f"duplicate macro {macro.name}",
                    macro.span.line,
                    macro.span.column,
                    macro.span.source,
                )
            seen.add(macro.name)
            if len(set(macro.params)) != len(macro.params):
                raise SemanticError(
                    f"duplicate macro parameter in {macro.name}",
                    macro.span.line,
                    macro.span.column,
                    macro.span.source,
                )
            if macro.is_expression_macro:
                continue
            for stmt in macro.body:
                if not isinstance(stmt, (ExprStmt, CoreDirective)):
                    raise SemanticError(
                        f"statement macro {macro.name} may only contain expression statements or Core directives; use `return expr;` for an expression macro",
                        stmt.span.line,
                        stmt.span.column,
                        stmt.span.source,
                    )

    def _expand_statements(self, body: list[Node], module: Module, stack: list[tuple[Path, str]], *, top_level: bool = False) -> list[Node]:
        result: list[Node] = []
        for stmt in body:
            if isinstance(stmt, Macro):
                continue

            if isinstance(stmt, ExprStmt) and isinstance(stmt.expr, Call):
                macro = self._resolve_macro(stmt.expr, module)
                if macro is not None:
                    if top_level:
                        raise SemanticError(
                            f"macro invocation {macro.name} is only allowed inside a function",
                            stmt.span.line, stmt.span.column, stmt.span.source,
                        )
                    macro_module = self._resolve_macro_module(stmt.expr, module)
                    assert macro_module is not None
                    key = (macro_module.path, macro.name)
                    if key in stack:
                        raise SemanticError(
                            f"cyclic macro expansion detected for {macro.name}",
                            stmt.expr.span.line,
                            stmt.expr.span.column,
                            stmt.expr.span.source,
                        )
                    if len(stmt.expr.args) != len(macro.params):
                        raise SemanticError(
                            f"wrong number of arguments for macro {macro.name}: expected {len(macro.params)}, got {len(stmt.expr.args)}",
                            stmt.expr.span.line,
                            stmt.expr.span.column,
                            stmt.expr.span.source,
                        )
                    bindings = dict(zip(macro.params, [self._expand_expr(a, module, {}, stack) for a in stmt.expr.args]))
                    if macro.is_expression_macro:
                        expr = self._expand_expr(macro.body[0].expr, macro_module, bindings, stack + [key])
                        result.append(ExprStmt(stmt.span, expr))
                    else:
                        expanded = self._expand_statements(
                            [self._substitute_stmt(s, bindings, macro_module) for s in macro.body],
                            macro_module,
                            stack + [key],
                            top_level=False,
                        )
                        result.extend(expanded)
                    continue

            result.append(self._expand_stmt(stmt, module, stack))
        return result

    def _expand_stmt(self, stmt: Node, module: Module, stack: list[tuple[Path, str]]) -> Node:
        if isinstance(stmt, Function):
            return Function(
                stmt.span,
                stmt.name,
                stmt.params,
                stmt.return_type,
                self._expand_statements(stmt.body, module, stack, top_level=False),
                stmt.is_async,
            )
        if isinstance(stmt, Let):
            return Let(stmt.span, stmt.name, stmt.type_name, self._expand_expr(stmt.expr, module, {}, stack))
        if isinstance(stmt, Assign):
            return Assign(stmt.span, stmt.name, self._expand_expr(stmt.expr, module, {}, stack))
        if isinstance(stmt, Return):
            return Return(stmt.span, self._expand_expr(stmt.expr, module, {}, stack) if stmt.expr else None)
        if isinstance(stmt, ExprStmt):
            return ExprStmt(stmt.span, self._expand_expr(stmt.expr, module, {}, stack))
        if isinstance(stmt, If):
            return If(
                stmt.span,
                self._expand_expr(stmt.condition, module, {}, stack),
                self._expand_statements(stmt.then_body, module, stack),
                None if stmt.else_body is None else self._expand_statements(stmt.else_body, module, stack),
            )
        if isinstance(stmt, While):
            return While(
                stmt.span,
                self._expand_expr(stmt.condition, module, {}, stack),
                self._expand_statements(stmt.body, module, stack),
            )
        if isinstance(stmt, For):
            init = self._expand_stmt(stmt.init, module, stack) if stmt.init else None
            condition = self._expand_expr(stmt.condition, module, {}, stack) if stmt.condition else None
            update = self._expand_stmt(stmt.update, module, stack) if stmt.update else None
            return For(
                stmt.span,
                init,
                condition,
                update,
                self._expand_statements(stmt.body, module, stack),
            )
        return stmt

    def _expand_expr(self, node: Node, module: Module, bindings: dict[str, Node], stack: list[tuple[Path, str]]) -> Node:
        if isinstance(node, Name):
            if node.value in bindings:
                return self._expand_expr(bindings[node.value], module, {}, stack)
            return node
        if isinstance(node, Literal):
            return node
        if isinstance(node, Await):
            return Await(node.span, self._expand_expr(node.expr, module, bindings, stack))
        if isinstance(node, Unary):
            return Unary(node.span, node.op, self._expand_expr(node.operand, module, bindings, stack))
        if isinstance(node, Binary):
            return Binary(
                node.span,
                self._expand_expr(node.left, module, bindings, stack),
                node.op,
                self._expand_expr(node.right, module, bindings, stack),
            )
        if isinstance(node, CollectionLiteral):
            return CollectionLiteral(
                node.span,
                node.kind,
                [
                    (self._expand_expr(k, module, bindings, stack), None if v is None else self._expand_expr(v, module, bindings, stack))
                    for k, v in node.items
                ],
            )
        if isinstance(node, NewExpr):
            return NewExpr(node.span, node.type_name, [self._expand_expr(a, module, bindings, stack) for a in node.args])
        if isinstance(node, Index):
            return Index(node.span, self._expand_expr(node.base, module, bindings, stack), self._expand_expr(node.index, module, bindings, stack))
        if isinstance(node, Member):
            return Member(node.span, self._expand_expr(node.base, module, bindings, stack), node.name)
        if isinstance(node, MemberCall):
            return MemberCall(node.span, self._expand_expr(node.base, module, bindings, stack), node.name, [self._expand_expr(a, module, bindings, stack) for a in node.args])
        if isinstance(node, Call):
            args = [self._expand_expr(a, module, bindings, stack) for a in node.args]
            macro = self._resolve_macro(node, module)
            if macro is None:
                return Call(node.span, node.parts, args)

            macro_module = self._resolve_macro_module(node, module)
            assert macro_module is not None
            key = (macro_module.path, macro.name)
            if key in stack:
                raise SemanticError(
                    f"cyclic macro expansion detected for {macro.name}",
                    node.span.line,
                    node.span.column,
                    node.span.source,
                )
            if not macro.is_expression_macro:
                raise SemanticError(
                    f"statement macro {macro.name} cannot be used in an expression",
                    node.span.line,
                    node.span.column,
                    node.span.source,
                )
            if len(args) != len(macro.params):
                raise SemanticError(
                    f"wrong number of arguments for macro {macro.name}: expected {len(macro.params)}, got {len(args)}",
                    node.span.line,
                    node.span.column,
                    node.span.source,
                )
            bindings2 = dict(zip(macro.params, args))
            substituted = self._substitute_expr(macro.body[0].expr, bindings2, macro_module)
            return self._expand_expr(substituted, macro_module, {}, stack + [key])
        return node

    def _substitute_stmt(self, stmt: Node, bindings: dict[str, Node], macro_module: Module) -> Node:
        if isinstance(stmt, ExprStmt):
            return ExprStmt(stmt.span, self._substitute_expr(stmt.expr, bindings, macro_module))
        return stmt

    def _substitute_expr(self, node: Node, bindings: dict[str, Node], macro_module: Module) -> Node:
        if isinstance(node, Name) and node.value in bindings:
            return bindings[node.value]
        if isinstance(node, Await):
            return Await(node.span, self._substitute_expr(node.expr, bindings, macro_module))
        if isinstance(node, Unary):
            return Unary(node.span, node.op, self._substitute_expr(node.operand, bindings, macro_module))
        if isinstance(node, Binary):
            return Binary(
                node.span,
                self._substitute_expr(node.left, bindings, macro_module),
                node.op,
                self._substitute_expr(node.right, bindings, macro_module),
            )
        if isinstance(node, CollectionLiteral):
            return CollectionLiteral(
                node.span,
                node.kind,
                [
                    (self._substitute_expr(k, bindings, macro_module), None if v is None else self._substitute_expr(v, bindings, macro_module))
                    for k, v in node.items
                ],
            )
        if isinstance(node, NewExpr):
            return NewExpr(node.span, node.type_name, [self._substitute_expr(a, bindings, macro_module) for a in node.args])
        if isinstance(node, Index):
            return Index(node.span, self._substitute_expr(node.base, bindings, macro_module), self._substitute_expr(node.index, bindings, macro_module))
        if isinstance(node, Member):
            return Member(node.span, self._substitute_expr(node.base, bindings, macro_module), node.name)
        if isinstance(node, MemberCall):
            return MemberCall(node.span, self._substitute_expr(node.base, bindings, macro_module), node.name, [self._substitute_expr(a, bindings, macro_module) for a in node.args])
        if isinstance(node, Call):
            parts = list(node.parts)
            if len(parts) == 1 and parts[0] != "echo" and parts[0] in macro_module.functions and parts[0] not in macro_module.macros:
                parts = [macro_module.name, parts[0]]
            return Call(node.span, parts, [self._substitute_expr(a, bindings, macro_module) for a in node.args])
        return node

    def _resolve_macro_module(self, call: Call, module: Module) -> Module | None:
        local_macros = self.registry.get(module.path, {})
        if len(call.parts) == 1:
            return module if call.parts[0] in local_macros else None
        prefix = tuple(call.parts[:-1])
        target = next((child for child in module.imports if child.qualified_name == prefix), None)
        if target is None or call.parts[-1] not in self.registry.get(target.path, {}):
            return None
        return target

    def _resolve_macro(self, call: Call, module: Module) -> Macro | None:
        target = self._resolve_macro_module(call, module)
        if target is None:
            return None
        return self.registry[target.path][call.parts[-1]]


BUILTIN_TYPES = {
    "int": "int",
    "long": "long long",
    "float": "float",
    "double": "double",
    "string": "std::string",
    "String": "std::string",
    "bool": "bool",
    "boolean": "bool",
    "char": "char",
    "void": "void",
    "auto": "auto",
}

TYPE_ALIASES = {"String": "string", "boolean": "bool"}
COLLECTION_ARITY = {"List": 1, "Set": 1, "Map": 2}


def split_generic_type(type_name: str) -> tuple[str, list[str]]:
    if "<" not in type_name:
        return type_name, []
    if not type_name.endswith(">"):
        return type_name, []
    base, raw = type_name.split("<", 1)
    raw = raw[:-1]
    args: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(raw):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(raw[start:i])
            start = i + 1
    args.append(raw[start:])
    return base, [a.strip() for a in args if a.strip()]


def normalize_type(type_name: str | None) -> str | None:
    if type_name is None:
        return None
    alias = TYPE_ALIASES.get(type_name)
    if alias:
        return alias
    base, args = split_generic_type(type_name)
    if args:
        normalized = [normalize_type(a) or a for a in args]
        return f"{base}<{','.join(normalized)}>"
    return base


@dataclass(frozen=True)
class FunctionSig:
    params: tuple[str | None, ...]
    return_type: str | None
    is_async: bool = False


class Analyzer:
    """Nominal type checker for the bootstrap language.

    M0.7 keeps the type model intentionally small and Java-like:
      int, long, float, double, bool, char, string, void

    M0.8 adds parameterized runtime collections:
      List<T>, Map<K,V>, Set<T>

    There are no user-defined classes, inheritance, or generics on functions yet.
    """

    NUMERIC_RANK = {"char": 0, "int": 1, "long": 2, "float": 3, "double": 4}

    def __init__(self, root: Module):
        self.root = root
        self.signatures: dict[tuple[Path, str], FunctionSig] = {}
        self.function_types: dict[tuple[Path, str], str] = {}
        self.current_function_async = False
        self.expr_types: dict[int, str] = {}

    def analyze(self) -> None:
        modules = self._all_modules(self.root)
        self._collect_declarations(modules)
        self._infer_returns(modules)
        for module in modules:
            self._analyze_module(module, require_main=(module is self.root))

    def _all_modules(self, root: Module) -> list[Module]:
        out: list[Module] = []
        seen: set[Path] = set()

        def visit(module: Module) -> None:
            if module.path in seen:
                return
            seen.add(module.path)
            for child in module.imports:
                visit(child)
            out.append(module)

        visit(root)
        return out

    def _collect_declarations(self, modules: list[Module]) -> None:
        for module in modules:
            seen: set[str] = set()
            for stmt in module.program.statements:
                if not isinstance(stmt, Function):
                    continue
                if stmt.name in seen:
                    raise SemanticError(f"duplicate function {stmt.name}", stmt.span.line, stmt.span.column, stmt.span.source)
                seen.add(stmt.name)
                param_types: list[str | None] = []
                seen_params: set[str] = set()
                for param in stmt.params:
                    if param.name in seen_params:
                        raise SemanticError(f"duplicate parameter {param.name}", param.span.line, param.span.column, param.span.source)
                    seen_params.add(param.name)
                    self._validate_type_name(param.type_name, param.span)
                    param_types.append(normalize_type(param.type_name))
                self._validate_type_name(stmt.return_type, stmt.span, allow_void=True)
                canonical_return = normalize_type(stmt.return_type)
                self.signatures[(module.path, stmt.name)] = FunctionSig(tuple(param_types), canonical_return, stmt.is_async)
                if module is self.root and stmt.name == "main" and stmt.return_type is None:
                    self.function_types[(module.path, stmt.name)] = "int"
                else:
                    self.function_types[(module.path, stmt.name)] = canonical_return or "auto"
            if module is self.root and "main" not in seen:
                raise SemanticError("program must define function main()", module.program.span.line, module.program.span.column, module.program.span.source)
            if module is self.root:
                fn = module.functions["main"]
                if fn.params:
                    raise SemanticError("function main() must not take parameters", fn.span.line, fn.span.column, fn.span.source)
                if normalize_type(fn.return_type) not in (None, "int"):
                    raise SemanticError("function main() must return int", fn.span.line, fn.span.column, fn.span.source)
                if fn.is_async:
                    raise SemanticError("function main() cannot be async", fn.span.line, fn.span.column, fn.span.source)

    def _validate_type_name(self, type_name: str | None, span: Span, *, allow_void: bool = False) -> None:
        normalized = normalize_type(type_name)
        if normalized is None:
            return
        if normalized in {"void", "auto"}:
            if normalized == "void" and allow_void:
                return
            if normalized == "auto":
                raise SemanticError("auto is only available for inferred local variables", span.line, span.column, span.source)
            raise SemanticError("void is not allowed here", span.line, span.column, span.source)
        if normalized in {"int", "long", "float", "double", "string", "bool", "char"}:
            return
        base, args = split_generic_type(normalized)
        if base in COLLECTION_ARITY:
            if len(args) != COLLECTION_ARITY[base]:
                raise SemanticError(f"{base} expects {COLLECTION_ARITY[base]} type argument(s)", span.line, span.column, span.source)
            for arg in args:
                self._validate_type_name(arg, span)
            return
        raise SemanticError(f"unknown type {type_name}", span.line, span.column, span.source)

    def _infer_returns(self, modules: list[Module]) -> None:
        for _ in range(len(modules) * 2 + 2):
            changed = False
            for module in modules:
                included = {child.name: child for child in module.imports}
                for fn in module.functions.values():
                    key = (module.path, fn.name)
                    if fn is module.functions.get("main") and module is self.root and fn.return_type is None:
                        self.function_types[key] = "int"
                        continue
                    if fn.return_type is not None:
                        self.function_types[key] = normalize_type(fn.return_type) or "void"
                        continue
                    scope = [self._param_scope(fn)]
                    return_types: list[str] = []
                    previous_async = self.current_function_async
                    self.current_function_async = fn.is_async
                    self._collect_return_types(fn.body, scope, module, included, return_types)
                    self.current_function_async = previous_async
                    if not return_types:
                        inferred = "void"
                    elif all(t != "auto" and t == return_types[0] for t in return_types):
                        inferred = return_types[0]
                    elif all(self._numeric(t) for t in return_types):
                        inferred = max(return_types, key=lambda t: self.NUMERIC_RANK[t])
                    else:
                        inferred = "auto"
                    if inferred != self.function_types.get(key):
                        self.function_types[key] = inferred
                        changed = True
            if not changed:
                break

        for module in modules:
            for fn in module.functions.values():
                typ = self.function_types[(module.path, fn.name)]
                if typ == "auto":
                    raise SemanticError(
                        f"cannot infer return type of {fn.name}; add an explicit return type with -> type",
                        fn.span.line,
                        fn.span.column,
                        fn.span.source,
                    )

    def _param_scope(self, fn: Function) -> dict[str, str]:
        return {p.name: (normalize_type(p.type_name) if p.type_name else "auto") for p in fn.params}

    def _collect_return_types(self, body: list[Node], scopes: list[dict[str, str]], module: Module, included: dict[str, Module], out: list[str]) -> None:
        for stmt in body:
            if isinstance(stmt, CoreDirective):
                if stmt.name == "__phead":
                    raise SemanticError("__phead is only valid at module scope", stmt.span.line, stmt.span.column, stmt.span.source)
                continue
            if isinstance(stmt, Let):
                if stmt.type_name:
                    self._validate_type_name(stmt.type_name, stmt.span)
                declared = normalize_type(stmt.type_name)
                expr_type = self._expr_type(stmt.expr, scopes, module, included, expected=declared)
                actual_declared = declared or expr_type
                if actual_declared == "void":
                    raise SemanticError("variables cannot have type void", stmt.span.line, stmt.span.column, stmt.span.source)
                if not self._assignable(actual_declared, expr_type):
                    self._type_mismatch(expr_type, actual_declared, stmt.span)
                scopes[-1][stmt.name] = actual_declared
            elif isinstance(stmt, Assign):
                target = self._lookup(scopes, stmt.name)
                if target is None:
                    raise SemanticError(f"unknown variable {stmt.name}", stmt.span.line, stmt.span.column, stmt.span.source)
                value_type = self._expr_type(stmt.expr, scopes, module, included, expected=target)
                if not self._assignable(target, value_type):
                    self._type_mismatch(value_type, target, stmt.span)
            elif isinstance(stmt, Return):
                out.append("void" if stmt.expr is None else self._expr_type(stmt.expr, scopes, module, included))
            elif isinstance(stmt, ExprStmt):
                self._expr_type(stmt.expr, scopes, module, included)
            elif isinstance(stmt, If):
                cond = self._expr_type(stmt.condition, scopes, module, included)
                self._require_bool(cond, stmt.condition.span, "if condition")
                scopes.append(dict(scopes[-1]))
                self._collect_return_types(stmt.then_body, scopes, module, included, out)
                scopes.pop()
                if stmt.else_body is not None:
                    scopes.append(dict(scopes[-1]))
                    self._collect_return_types(stmt.else_body, scopes, module, included, out)
                    scopes.pop()
            elif isinstance(stmt, While):
                cond = self._expr_type(stmt.condition, scopes, module, included)
                self._require_bool(cond, stmt.condition.span, "while condition")
                scopes.append(dict(scopes[-1]))
                self._collect_return_types(stmt.body, scopes, module, included, out)
                scopes.pop()
            elif isinstance(stmt, For):
                scopes.append(dict(scopes[-1]))
                if stmt.init:
                    self._collect_return_types([stmt.init], scopes, module, included, out)
                if stmt.condition:
                    cond = self._expr_type(stmt.condition, scopes, module, included)
                    self._require_bool(cond, stmt.condition.span, "for condition")
                if stmt.update:
                    self._collect_return_types([stmt.update], scopes, module, included, out)
                self._collect_return_types(stmt.body, scopes, module, included, out)
                scopes.pop()

    def _analyze_module(self, module: Module, *, require_main: bool) -> None:
        included = {child.name: child for child in module.imports}
        for stmt in module.program.statements:
            if isinstance(stmt, CoreDirective) and module is not self.root:
                raise SemanticError(
                    f"top-level {stmt.name} is only allowed in the root source file; use it inside a function for module code",
                    stmt.span.line, stmt.span.column, stmt.span.source,
                )
        for fn in module.functions.values():
            scope: list[dict[str, str]] = [self._param_scope(fn)]
            expected = self.function_types[(module.path, fn.name)]
            previous_async = self.current_function_async
            self.current_function_async = fn.is_async
            self._analyze_statements(fn.body, scope, module, included, expected)
            self.current_function_async = previous_async
            if module is not self.root or fn.name != "main":
                if expected != "void" and not self._guarantees_return(fn.body):
                    raise SemanticError(
                        f"function {fn.name} may finish without returning {self._display_type(expected)}",
                        fn.span.line,
                        fn.span.column,
                        fn.span.source,
                    )

    def _analyze_statements(self, body: list[Node], scopes: list[dict[str, str]], module: Module, included: dict[str, Module], expected_return: str) -> None:
        for stmt in body:
            if isinstance(stmt, CoreDirective):
                if stmt.name == "__phead":
                    raise SemanticError("__phead is only valid at module scope", stmt.span.line, stmt.span.column, stmt.span.source)
                continue
            if isinstance(stmt, Let):
                if stmt.name in scopes[-1]:
                    raise SemanticError(f"variable {stmt.name} already defined in this scope", stmt.span.line, stmt.span.column, stmt.span.source)
                if stmt.type_name:
                    self._validate_type_name(stmt.type_name, stmt.span)
                declared = normalize_type(stmt.type_name)
                expr_type = self._expr_type(stmt.expr, scopes, module, included, expected=declared)
                actual_declared = declared or expr_type
                if actual_declared == "void":
                    raise SemanticError("variables cannot have type void", stmt.span.line, stmt.span.column, stmt.span.source)
                if not self._assignable(actual_declared, expr_type):
                    self._type_mismatch(expr_type, actual_declared, stmt.span)
                scopes[-1][stmt.name] = actual_declared
                continue

            if isinstance(stmt, Assign):
                target = self._lookup(scopes, stmt.name)
                if target is None:
                    raise SemanticError(f"unknown variable {stmt.name}", stmt.span.line, stmt.span.column, stmt.span.source)
                value_type = self._expr_type(stmt.expr, scopes, module, included, expected=target)
                if not self._assignable(target, value_type):
                    self._type_mismatch(value_type, target, stmt.span)
                continue

            if isinstance(stmt, Return):
                actual = "void" if stmt.expr is None else self._expr_type(stmt.expr, scopes, module, included, expected=expected_return)
                if not self._assignable(expected_return, actual):
                    self._type_mismatch(actual, expected_return, stmt.span)
                continue

            if isinstance(stmt, ExprStmt):
                self._expr_type(stmt.expr, scopes, module, included)
                continue

            if isinstance(stmt, If):
                cond = self._expr_type(stmt.condition, scopes, module, included)
                self._require_bool(cond, stmt.condition.span, "if condition")
                scopes.append({})
                self._analyze_statements(stmt.then_body, scopes, module, included, expected_return)
                scopes.pop()
                if stmt.else_body is not None:
                    scopes.append({})
                    self._analyze_statements(stmt.else_body, scopes, module, included, expected_return)
                    scopes.pop()
                continue

            if isinstance(stmt, While):
                cond = self._expr_type(stmt.condition, scopes, module, included)
                self._require_bool(cond, stmt.condition.span, "while condition")
                scopes.append({})
                self._analyze_statements(stmt.body, scopes, module, included, expected_return)
                scopes.pop()
                continue

            if isinstance(stmt, For):
                scopes.append({})
                if stmt.init:
                    self._analyze_statements([stmt.init], scopes, module, included, expected_return)
                if stmt.condition:
                    cond = self._expr_type(stmt.condition, scopes, module, included)
                    self._require_bool(cond, stmt.condition.span, "for condition")
                if stmt.update:
                    self._analyze_statements([stmt.update], scopes, module, included, expected_return)
                self._analyze_statements(stmt.body, scopes, module, included, expected_return)
                scopes.pop()
                continue

            raise SemanticError(f"unsupported statement {type(stmt).__name__}", stmt.span.line, stmt.span.column, stmt.span.source)

    def _guarantees_return(self, body: list[Node]) -> bool:
        for stmt in body:
            if isinstance(stmt, Return):
                return True
            if isinstance(stmt, If):
                if stmt.else_body is not None and self._guarantees_return(stmt.then_body) and self._guarantees_return(stmt.else_body):
                    return True
        return False

    def _lookup(self, scopes: list[dict[str, str]], name: str) -> str | None:
        for scope in reversed(scopes):
            if name in scope:
                return scope[name]
        return None

    def _signature(self, module: Module, name: str) -> FunctionSig:
        return self.signatures[(module.path, name)]

    def _expr_type(
        self,
        node: Node,
        scopes: list[dict[str, str]],
        module: Module,
        included: dict[str, Module],
        expected: str | None = None,
    ) -> str:
        result = self._expr_type_impl(node, scopes, module, included, expected)
        self.expr_types[id(node)] = result
        return result

    def _expr_type_impl(
        self,
        node: Node,
        scopes: list[dict[str, str]],
        module: Module,
        included: dict[str, Module],
        expected: str | None = None,
    ) -> str:
        if isinstance(node, CoreDirective):
            raise SemanticError(f"{node.name} cannot be used as an expression", node.span.line, node.span.column, node.span.source)
        if isinstance(node, Await):
            inner = self._expr_type(node.expr, scopes, module, included)
            base, args = split_generic_type(inner)
            if base != "future" or len(args) != 1:
                raise SemanticError("await requires an async task/future", node.span.line, node.span.column, node.span.source)
            return args[0]
        if isinstance(node, Literal):
            return {"int": "int", "float": "double", "float32": "float", "string": "string", "bool": "bool", "char": "char"}[node.kind]
        if isinstance(node, Name):
            value = self._lookup(scopes, node.value)
            if value is None:
                raise SemanticError(f"unknown name {node.value}", node.span.line, node.span.column, node.span.source)
            return value
        if isinstance(node, Unary):
            typ = self._expr_type(node.operand, scopes, module, included)
            if node.op == "!":
                self._require_bool(typ, node.span, "! operand")
                return "bool"
            if not self._numeric(typ):
                raise SemanticError(f"unary {node.op} requires a numeric operand", node.span.line, node.span.column, node.span.source)
            return typ
        if isinstance(node, Binary):
            left = self._expr_type(node.left, scopes, module, included)
            right = self._expr_type(node.right, scopes, module, included)
            if node.op in {"&&", "||"}:
                self._require_bool(left, node.left.span, f"left operand of {node.op}")
                self._require_bool(right, node.right.span, f"right operand of {node.op}")
                return "bool"
            if node.op in {"==", "!="}:
                if not self._comparable(left, right):
                    raise SemanticError(f"cannot compare {self._display_type(left)} and {self._display_type(right)}", node.span.line, node.span.column, node.span.source)
                return "bool"
            if node.op in {"<", "<=", ">", ">="}:
                if not self._numeric(left) or not self._numeric(right):
                    raise SemanticError(f"operator {node.op} requires numeric operands", node.span.line, node.span.column, node.span.source)
                return "bool"

            if node.op == "+" and left == "string" and right == "string":
                return "string"
            if not self._numeric(left) or not self._numeric(right):
                raise SemanticError(f"operator {node.op} requires numeric operands", node.span.line, node.span.column, node.span.source)
            return self._numeric_promote(left, right)
        if isinstance(node, CollectionLiteral):
            return self._collection_literal_type(node, scopes, module, included, expected)
        if isinstance(node, NewExpr):
            typ = normalize_type(node.type_name)
            self._validate_type_name(typ, node.span)
            base, _ = split_generic_type(typ or "")
            if base not in COLLECTION_ARITY:
                raise SemanticError("new currently supports List<T>, Map<K,V>, and Set<T>", node.span.line, node.span.column, node.span.source)
            if node.args:
                raise SemanticError(f"{base} constructor currently takes no arguments", node.span.line, node.span.column, node.span.source)
            return typ or "auto"
        if isinstance(node, Index):
            base_type = self._expr_type(node.base, scopes, module, included)
            index_type = self._expr_type(node.index, scopes, module, included)
            base, args = split_generic_type(base_type)
            if base == "List":
                if not self._assignable("int", index_type):
                    raise SemanticError("List index must be int", node.index.span.line, node.index.span.column, node.index.span.source)
                return args[0]
            if base == "Map":
                if len(args) != 2 or not self._assignable(args[0], index_type):
                    raise SemanticError(f"Map index must be {self._display_type(args[0])}", node.index.span.line, node.index.span.column, node.index.span.source)
                return args[1]
            raise SemanticError(f"type {self._display_type(base_type)} is not indexable", node.base.span.line, node.base.span.column, node.base.span.source)
        if isinstance(node, MemberCall):
            base_type = self._expr_type(node.base, scopes, module, included)
            base, type_args = split_generic_type(base_type)
            arg_types = [self._expr_type(a, scopes, module, included) for a in node.args]
            if base == "List" and len(type_args) == 1:
                element = type_args[0]
                if node.name == "add" and len(arg_types) == 1:
                    self._check_member_arg(arg_types[0], node.args[0], element)
                    return "void"
                if node.name == "get" and len(arg_types) == 1:
                    self._require_int_arg(arg_types[0], node)
                    return element
                if node.name == "size" and len(arg_types) == 0:
                    return "int"
                if node.name == "contains" and len(arg_types) == 1:
                    self._check_member_arg(arg_types[0], node.args[0], element)
                    return "bool"
            if base == "Map" and len(type_args) == 2:
                key_type, value_type = type_args
                if node.name == "put" and len(arg_types) == 2:
                    self._check_member_arg(arg_types[0], node.args[0], key_type)
                    self._check_member_arg(arg_types[1], node.args[1], value_type)
                    return "void"
                if node.name == "get" and len(arg_types) == 1:
                    self._check_member_arg(arg_types[0], node.args[0], key_type)
                    return value_type
                if node.name == "size" and len(arg_types) == 0:
                    return "int"
                if node.name == "contains" and len(arg_types) == 1:
                    self._check_member_arg(arg_types[0], node.args[0], key_type)
                    return "bool"
            if base == "Set" and len(type_args) == 1:
                element = type_args[0]
                if node.name == "add" and len(arg_types) == 1:
                    self._check_member_arg(arg_types[0], node.args[0], element)
                    return "void"
                if node.name == "contains" and len(arg_types) == 1:
                    self._check_member_arg(arg_types[0], node.args[0], element)
                    return "bool"
                if node.name == "remove" and len(arg_types) == 1:
                    self._check_member_arg(arg_types[0], node.args[0], element)
                    return "void"
                if node.name == "size" and len(arg_types) == 0:
                    return "int"
            raise SemanticError(f"type {self._display_type(base_type)} has no method {node.name} with {len(node.args)} argument(s)", node.span.line, node.span.column, node.span.source)
        if isinstance(node, Member):
            raise SemanticError(f"member access .{node.name} is not readable without a method call", node.span.line, node.span.column, node.span.source)
        if isinstance(node, Call):
            if len(node.parts) == 1 and node.parts[0] == "sleep":
                if len(node.args) != 1:
                    raise SemanticError("sleep expects exactly one argument", node.span.line, node.span.column, node.span.source)
                actual = self._expr_type(node.args[0], scopes, module, included)
                if not self._assignable("int", actual):
                    self._type_mismatch(actual, "int", node.args[0].span)
                return "void"
            if len(node.parts) == 1 and node.parts[0] == "echo":
                if len(node.args) != 1:
                    raise SemanticError("echo expects exactly one argument", node.span.line, node.span.column, node.span.source)
                value_type = self._expr_type(node.args[0], scopes, module, included)
                if value_type.startswith("future<"):
                    raise SemanticError("cannot echo an async task; use await", node.args[0].span.line, node.args[0].span.column, node.args[0].span.source)
                if split_generic_type(value_type)[0] in COLLECTION_ARITY:
                    raise SemanticError("echo does not support collection values yet", node.args[0].span.line, node.args[0].span.column, node.args[0].span.source)
                return "void"
            target_module = module
            if len(node.parts) >= 2:
                prefix = tuple(node.parts[:-1])
                target_module = next((child for child in module.imports if child.qualified_name == prefix), None)
                if target_module is None:
                    raise SemanticError(f"module {'::'.join(node.parts[:-1])} is not directly included", node.span.line, node.span.column, node.span.source)
            target_name = node.parts[-1]
            if target_name not in target_module.functions:
                raise SemanticError(f"module {target_module.name} has no function {target_name}", node.span.line, node.span.column, node.span.source)
            sig = self._signature(target_module, target_name)
            if len(node.args) != len(sig.params):
                raise SemanticError(
                    f"wrong number of arguments for {target_name}: expected {len(sig.params)}, got {len(node.args)}",
                    node.span.line, node.span.column, node.span.source,
                )
            for arg, expected_type in zip(node.args, sig.params):
                actual = self._expr_type(arg, scopes, module, included, expected=expected_type)
                if expected_type and not self._assignable(expected_type, actual):
                    self._type_mismatch(actual, expected_type, arg.span)
            underlying = self.function_types[(target_module.path, target_name)]
            return f"future<{underlying}>" if sig.is_async else underlying
        raise SemanticError(f"unsupported expression {type(node).__name__}", node.span.line, node.span.column, node.span.source)

    def _collection_literal_type(self, node: CollectionLiteral, scopes: list[dict[str, str]], module: Module, included: dict[str, Module], expected: str | None) -> str:
        expected = normalize_type(expected)
        if node.kind == "list":
            if expected and split_generic_type(expected)[0] in {"List", "Set"}:
                expected_base, expected_args = split_generic_type(expected)
                if len(expected_args) != 1:
                    raise SemanticError(f"{expected_base} expects one element type", node.span.line, node.span.column, node.span.source)
                element_type = expected_args[0]
                for value, _ in node.items:
                    actual = self._expr_type(value, scopes, module, included, expected=element_type)
                    if not self._assignable(element_type, actual):
                        self._type_mismatch(actual, element_type, value.span)
                return expected
            if not node.items:
                raise SemanticError("empty collection literal requires an explicit List<T> or Set<T> type", node.span.line, node.span.column, node.span.source)
            types = [self._expr_type(value, scopes, module, included) for value, _ in node.items]
            if all(t == types[0] for t in types):
                return f"List<{types[0]}>"
            if all(self._numeric(t) for t in types):
                return f"List<{max(types, key=lambda t: self.NUMERIC_RANK[t])}>"
            raise SemanticError("collection literal elements must have a compatible type", node.span.line, node.span.column, node.span.source)
        if node.kind == "map":
            if expected and split_generic_type(expected)[0] == "Map":
                _, expected_args = split_generic_type(expected)
                if len(expected_args) != 2:
                    raise SemanticError("Map expects key and value types", node.span.line, node.span.column, node.span.source)
                key_type, value_type = expected_args
                for key, value in node.items:
                    actual_key = self._expr_type(key, scopes, module, included, expected=key_type)
                    actual_value = self._expr_type(value, scopes, module, included, expected=value_type)
                    if not self._assignable(key_type, actual_key):
                        self._type_mismatch(actual_key, key_type, key.span)
                    if not self._assignable(value_type, actual_value):
                        self._type_mismatch(actual_value, value_type, value.span)
                return expected
            if not node.items:
                raise SemanticError("empty map literal requires an explicit Map<K,V> type", node.span.line, node.span.column, node.span.source)
            key_types = [self._expr_type(k, scopes, module, included) for k, _ in node.items]
            value_types = [self._expr_type(v, scopes, module, included) for _, v in node.items]
            if len(set(key_types)) == 1 and len(set(value_types)) == 1:
                return f"Map<{key_types[0]},{value_types[0]}>"
            raise SemanticError("map literal keys and values must have consistent types", node.span.line, node.span.column, node.span.source)
        raise SemanticError(f"unsupported collection literal {node.kind}", node.span.line, node.span.column, node.span.source)

    def _require_int_arg(self, typ: str, node: Node) -> None:
        if not self._assignable("int", typ):
            raise SemanticError("collection index must be int", node.span.line, node.span.column, node.span.source)

    def _check_member_arg(self, actual: str, arg_node: Node, expected: str) -> None:
        if not self._assignable(expected, actual):
            self._type_mismatch(actual, expected, arg_node.span)

    def _type_mismatch(self, actual: str, expected: str, span: Span) -> None:
        raise SemanticError(f"cannot assign {self._display_type(actual)} to {self._display_type(expected)}", span.line, span.column, span.source)

    def _assignable(self, expected: str, actual: str) -> bool:
        if expected == "auto" or actual == "auto":
            return True
        if expected == actual:
            return True
        if self._numeric(expected) and self._numeric(actual):
            return self.NUMERIC_RANK[actual] <= self.NUMERIC_RANK[expected]
        return False

    def _comparable(self, left: str, right: str) -> bool:
        if left == right:
            return True
        return self._numeric(left) and self._numeric(right)

    def _numeric(self, typ: str) -> bool:
        return typ in self.NUMERIC_RANK

    def _numeric_promote(self, left: str, right: str) -> str:
        return max((left, right), key=lambda t: self.NUMERIC_RANK[t])

    def _display_type(self, typ: str) -> str:
        base, args = split_generic_type(typ)
        if base == "future" and len(args) == 1:
            return f"future<{self._display_type(args[0])}>"
        if base in COLLECTION_ARITY:
            return f"{base}<" + ", ".join(self._display_type(a) for a in args) + ">"
        return BUILTIN_TYPES.get(typ, typ)

    def _require_bool(self, typ: str, span: Span, context: str) -> None:
        if typ not in {"bool", "auto"}:
            raise SemanticError(f"{context} must be bool, got {self._display_type(typ)}", span.line, span.column, span.source)

class Codegen:
    def __init__(self, root: Module, analyzer: Analyzer):
        self.root = root
        self.analyzer = analyzer
        self.lines: list[str] = []

    def emit(self, line: str = "") -> None:
        self.lines.append(line)

    def generate(self) -> str:
        extra_headers: list[str] = []
        root_eval: list[str] = []
        for stmt in self.root.program.statements:
            if isinstance(stmt, CoreDirective) and stmt.name == "__phead":
                if stmt.value not in extra_headers:
                    extra_headers.append(stmt.value)
            elif isinstance(stmt, CoreDirective) and stmt.name == "__eval":
                root_eval.append(stmt.value)
        self.emit("#include <iostream>")
        self.emit("#include <string>")
        self.emit("#include <future>")
        self.emit("#include <thread>")
        self.emit("#include <chrono>")
        self.emit("#include <functional>")
        self.emit("#include <memory>")
        self.emit("#include <vector>")
        self.emit("#include <map>")
        self.emit("#include <set>")
        self.emit("#include <algorithm>")
        for header in extra_headers:
            self.emit(header)
        if root_eval:
            self.emit("")
            for raw in root_eval:
                for line in raw.splitlines() or [""]:
                    self.emit(line)
        self.emit("")
        self.emit("namespace raz {")
        self.emit("template <typename T> void echo(const T& value) { std::cout << value << std::endl; }")
        self.emit("inline void sleep(int seconds) { std::this_thread::sleep_for(std::chrono::seconds(seconds)); }")
        self.emit("class AsyncRegistry {")
        self.emit("public:")
        self.emit("    template <typename T> void keep(std::future<T> fut) {")
        self.emit("        auto shared = std::make_shared<std::future<T>>(std::move(fut));")
        self.emit("        waiters.push_back([shared] { shared->wait(); });")
        self.emit("    }")
        self.emit("    ~AsyncRegistry() { for (auto &wait : waiters) wait(); }")
        self.emit("private:")
        self.emit("    std::vector<std::function<void()>> waiters;")
        self.emit("};")
        self.emit("inline AsyncRegistry async_registry;")
        self.emit("template <typename T> void spawn(std::future<T> fut) { async_registry.keep(std::move(fut)); }")
        self.emit("}")
        self.emit("")

        modules = self._ordered_modules(self.root)

        # Declaration pass: make every function visible before emitting any body.
        for module in modules:
            if module is self.root:
                continue
            ns = "::".join(self._cpp_module_name(part) for part in module.qualified_name)
            self.emit(f"namespace {ns} {{")
            for fn in self._functions_in_source_order(module):
                self.emit(self.declaration(fn, module))
            self.emit("}")
            self.emit("")

        for fn in self._functions_in_source_order(self.root):
            self.emit(self.declaration(fn, self.root))
        self.emit("")

        # Definition pass: source order is now safe because declarations exist.
        for module in modules:
            if module is self.root:
                continue
            ns = "::".join(self._cpp_module_name(part) for part in module.qualified_name)
            self.emit(f"namespace {ns} {{")
            for fn in self._functions_in_source_order(module):
                self.function(fn, module)
            self.emit("}")
            self.emit("")

        for fn in self._functions_in_source_order(self.root):
            self.function(fn, self.root)

        self.emit("int main() {")
        self.emit("    return raz_main();")
        self.emit("}")
        return "\n".join(self.lines) + "\n"

    @staticmethod
    def _functions_in_source_order(module: Module) -> list[Function]:
        return [stmt for stmt in module.program.statements if isinstance(stmt, Function)]

    def declaration(self, fn: Function, module: Module) -> str:
        emitted_name = "raz_main" if module is self.root and fn.name == "main" else fn.name
        ret = self.analyzer.function_types[(module.path, fn.name)]
        params = ", ".join(f"{self._cpp_type(p.type_name or 'auto')} {p.name}" for p in fn.params)
        if fn.is_async:
            ret = f"std::future<{ret}>"
        return f"{ret} {emitted_name}({params});"

    def _ordered_modules(self, root: Module) -> list[Module]:
        out: list[Module] = []
        seen: set[Path] = set()

        def visit(module: Module) -> None:
            if module.path in seen:
                return
            seen.add(module.path)
            for child in module.imports:
                visit(child)
            out.append(module)

        visit(root)
        return out

    def function(self, fn: Function, module: Module) -> None:
        emitted_name = "raz_main" if module is self.root and fn.name == "main" else fn.name
        ret = self.analyzer.function_types[(module.path, fn.name)]
        params = ", ".join(f"{self._cpp_type(p.type_name or 'auto')} {p.name}" for p in fn.params)
        if fn.is_async:
            captures = ", ".join(p.name for p in fn.params)
            capture = "[" + captures + "]" if captures else "[]"
            self.emit(f"std::future<{ret}> {emitted_name}({params}) {{")
            self.emit(f"    return std::async(std::launch::async, {capture}, [this]() {{}});".replace("[this]", ""))
            # Replace the temporary lambda line with a lambda whose body is emitted below.
            self.lines.pop()
            self.emit(f"    return std::async(std::launch::async, {capture}() -> {ret} {{")
            for stmt in fn.body:
                self.statement(stmt, 2, module)
            if ret == "void" and not any(isinstance(x, Return) for x in fn.body):
                self.emit("        return;")
            self.emit("    });")
            self.emit("}")
            self.emit("")
            return
        self.emit(f"{ret} {emitted_name}({params}) {{")
        for stmt in fn.body:
            self.statement(stmt, 1, module)
        if module is self.root and fn.name == "main" and ret == "int" and not any(isinstance(x, Return) for x in fn.body):
            self.emit("    return 0;")
        self.emit("}")
        self.emit("")

    def statement(self, stmt: Node, indent: int, module: Module) -> None:
        pad = "    " * indent
        if isinstance(stmt, CoreDirective):
            if stmt.name == "__eval":
                for line in stmt.value.splitlines() or [""]:
                    self.emit(pad + line if line else "")
            return
        if isinstance(stmt, Let):
            typ = self._cpp_type(stmt.type_name) if stmt.type_name else "auto"
            expr = self.expr(stmt.expr, module, expected_type=stmt.type_name)
            self.emit(f"{pad}{typ} {stmt.name} = {expr};")
        elif isinstance(stmt, Assign):
            self.emit(f"{pad}{stmt.name} = {self.expr(stmt.expr, module)};")
        elif isinstance(stmt, Return):
            self.emit(f"{pad}return" + (f" {self.expr(stmt.expr, module)}" if stmt.expr else "") + ";")
        elif isinstance(stmt, ExprStmt):
            if isinstance(stmt.expr, Call):
                callee_module = module
                if len(stmt.expr.parts) >= 2:
                    callee_module = next((m for m in module.imports if m.qualified_name == tuple(stmt.expr.parts[:-1])), module)
                target = self.analyzer.signatures.get((callee_module.path, stmt.expr.parts[-1]))
                if target is not None and target.is_async:
                    self.emit(pad + "raz::spawn(" + self.expr(stmt.expr, module) + ");")
                else:
                    self.emit(pad + self.expr(stmt.expr, module) + ";")
            else:
                self.emit(pad + self.expr(stmt.expr, module) + ";")
        elif isinstance(stmt, If):
            self._emit_if(stmt, indent, module)
        elif isinstance(stmt, While):
            self.emit(f"{pad}while ({self.expr(stmt.condition, module)}) {{")
            for child in stmt.body:
                self.statement(child, indent + 1, module)
            self.emit(f"{pad}}}")
        elif isinstance(stmt, For):
            init = self.inline_for_part(stmt.init, module) if stmt.init else ""
            cond = self.expr(stmt.condition, module) if stmt.condition else "true"
            update = self.inline_for_part(stmt.update, module) if stmt.update else ""
            self.emit(f"{pad}for ({init}; {cond}; {update}) {{")
            for child in stmt.body:
                self.statement(child, indent + 1, module)
            self.emit(f"{pad}}}")
        else:
            raise NotImplementedError(type(stmt).__name__)

    def _emit_if(self, node: If, indent: int, module: Module, prefix: str | None = None) -> None:
        pad = "    " * indent
        head = prefix if prefix is not None else pad
        self.emit(f"{head}if ({self.expr(node.condition, module)}) {{")
        for child in node.then_body:
            self.statement(child, indent + 1, module)
        self.emit(f"{pad}}}")
        if node.else_body is None:
            return
        if len(node.else_body) == 1 and isinstance(node.else_body[0], If):
            self._emit_if(node.else_body[0], indent, module, prefix=f"{pad}else ")
            return
        self.emit(f"{pad}else {{")
        for child in node.else_body:
            self.statement(child, indent + 1, module)
        self.emit(f"{pad}}}")

    def inline_for_part(self, node: Node | None, module: Module) -> str:
        if node is None:
            return ""
        if isinstance(node, Let):
            typ = self._cpp_type(node.type_name) if node.type_name else "auto"
            return f"{typ} {node.name} = {self.expr(node.expr, module, expected_type=node.type_name)}"
        if isinstance(node, Assign):
            return f"{node.name} = {self.expr(node.expr, module)}"
        if isinstance(node, ExprStmt):
            return self.expr(node.expr, module)
        raise NotImplementedError(type(node).__name__)

    def expr(self, node: Node, module: Module, expected_type: str | None = None) -> str:
        if isinstance(node, Literal):
            if node.kind == "string":
                return cpp_string(str(node.value))
            if node.kind == "char":
                value = str(node.value).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\t", "\\t")
                return f"'{value}'"
            if node.kind == "bool":
                return "true" if node.value else "false"
            return str(node.value)
        if isinstance(node, Name):
            return node.value
        if isinstance(node, Await):
            return f"({self.expr(node.expr, module)}.get())"
        if isinstance(node, Unary):
            return f"({node.op}{self.expr(node.operand, module)})"
        if isinstance(node, Binary):
            return f"({self.expr(node.left, module)} {node.op} {self.expr(node.right, module)})"
        if isinstance(node, Index):
            return f"{self.expr(node.base, module)}[{self.expr(node.index, module)}]"
        if isinstance(node, Member):
            return f"{self.expr(node.base, module)}.{node.name}"
        if isinstance(node, MemberCall):
            base = self.expr(node.base, module)
            args = ', '.join(self.expr(a, module) for a in node.args)
            # Raz collection API -> C++ STL operations.
            # Semantic analysis has already verified arity and types.
            base_kind, _ = split_generic_type(self._guess_collection_type(node.base, module))
            if base_kind == "List":
                if node.name == "add":
                    return f"{base}.push_back({args})"
                if node.name == "get":
                    return f"{base}[{args}]"
                if node.name == "size":
                    return f"{base}.size()"
                if node.name == "contains":
                    return f"(std::find({base}.begin(), {base}.end(), {args}) != {base}.end())"
            if base_kind == "Map":
                if node.name == "put":
                    a = [self.expr(x, module) for x in node.args]
                    return f"{base}[{a[0]}] = {a[1]}"
                if node.name == "get":
                    return f"{base}.at({args})"
                if node.name == "size":
                    return f"{base}.size()"
                if node.name == "contains":
                    return f"({base}.find({args}) != {base}.end())"
            if base_kind == "Set":
                if node.name == "add":
                    return f"{base}.insert({args})"
                if node.name == "contains":
                    return f"({base}.find({args}) != {base}.end())"
                if node.name == "remove":
                    return f"{base}.erase({args})"
                if node.name == "size":
                    return f"{base}.size()"
            return f"{base}.{node.name}({args})"
        if isinstance(node, NewExpr):
            cpp_t = self._cpp_type(node.type_name)
            return f"{cpp_t}{{{', '.join(self.expr(a, module) for a in node.args)}}}"
        if isinstance(node, CollectionLiteral):
            values = []
            for key, value in node.items:
                if node.kind == "map":
                    values.append(f"std::pair{{{self.expr(key, module)}, {self.expr(value, module)}}}")
                else:
                    values.append(self.expr(key, module))
            typ = (expected_type or "")
            base, type_args = split_generic_type(normalize_type(typ) or "")
            if node.kind == "map":
                if not values:
                    return f"{self._cpp_type(typ)}{{}}"
                return "std::map{" + ", ".join(values) + "}"
            if base == "Set":
                if not values:
                    return f"{self._cpp_type(typ)}{{}}"
                return "std::set{" + ", ".join(values) + "}"
            if not values:
                return f"{self._cpp_type(typ)}{{}}" if typ else "std::vector<int>{{}}"
            return "std::vector{" + ", ".join(values) + "}"
        if isinstance(node, Call):
            if len(node.parts) == 1:
                if node.parts[0] == "echo":
                    callee = "raz::echo"
                elif node.parts[0] == "sleep":
                    callee = "raz::sleep"
                else:
                    callee = "raz_main" if module is self.root and node.parts[0] == "main" else node.parts[0]
            else:
                callee = "::".join(self._cpp_module_name(part) for part in node.parts)
            return f"{callee}({', '.join(self.expr(a, module) for a in node.args)})"
        raise NotImplementedError(type(node).__name__)

    def _guess_collection_type(self, node: Node, module: Module) -> str:
        cached = self.analyzer.expr_types.get(id(node), "")
        if split_generic_type(cached)[0] in COLLECTION_ARITY:
            return cached
        if isinstance(node, NewExpr):
            typ = normalize_type(node.type_name) or ""
            if split_generic_type(typ)[0] in COLLECTION_ARITY:
                return typ
        return ""

    def _infer_local_expr_type(self, node: Node) -> str | None:
        if isinstance(node, NewExpr):
            return normalize_type(node.type_name)
        if isinstance(node, CollectionLiteral):
            if not node.items:
                return None
            if node.kind == "map":
                key, value = node.items[0]
                kt = self._infer_literal_simple_type(key)
                vt = self._infer_literal_simple_type(value) if value is not None else None
                if kt and vt:
                    return f"Map<{kt},{vt}>"
            else:
                t = self._infer_literal_simple_type(node.items[0][0])
                if t:
                    return f"List<{t}>"
        return None

    def _infer_literal_simple_type(self, node: Node) -> str | None:
        if isinstance(node, Literal):
            return {"int":"int", "float":"float", "string":"string", "bool":"bool", "char":"char"}.get(node.kind)
        return None

    @staticmethod
    def _cpp_type(type_name: str | None) -> str:
        if not type_name:
            return "auto"
        normalized = normalize_type(type_name) or type_name
        if normalized in BUILTIN_TYPES:
            return BUILTIN_TYPES[normalized]
        base, args = split_generic_type(normalized)
        if base == "List" and len(args) == 1:
            return f"std::vector<{Codegen._cpp_type(args[0])}>"
        if base == "Map" and len(args) == 2:
            return f"std::map<{Codegen._cpp_type(args[0])}, {Codegen._cpp_type(args[1])}>"
        if base == "Set" and len(args) == 1:
            return f"std::set<{Codegen._cpp_type(args[0])}>"
        if base == "future" and len(args) == 1:
            return f"std::future<{Codegen._cpp_type(args[0])}>"
        return type_name

    @staticmethod
    def _cpp_module_name(name: str) -> str:
        value = re.sub(r"\W", "_", name)
        if not value or value[0].isdigit():
            value = "m_" + value
        return value


def load_package_config(manifest: Path) -> PackageConfig:
    manifest = manifest.resolve()
    if not manifest.exists():
        raise RazError("package manifest not found", 1, 1, str(manifest))
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RazError(f"invalid package manifest: {exc.msg}", exc.lineno, exc.colno, str(manifest)) from exc
    if not isinstance(data, dict):
        raise RazError("package manifest must contain a JSON object", 1, 1, str(manifest))
    name = data.get("name")
    version = data.get("version", "0.0.0")
    if not isinstance(name, str) or not name.strip():
        raise RazError("package manifest requires a non-empty name", 1, 1, str(manifest))
    if not isinstance(version, str):
        raise RazError("package version must be a string", 1, 1, str(manifest))

    root = manifest.parent
    stdlib_value = data.get("stdlib", "stdlib")
    stdlib = (root / stdlib_value).resolve() if isinstance(stdlib_value, str) and stdlib_value else None

    roots_value = data.get("source_roots", ["src"])
    if not isinstance(roots_value, list) or not all(isinstance(item, str) for item in roots_value):
        raise RazError("source_roots must be an array of strings", 1, 1, str(manifest))
    source_roots = tuple((root / item).resolve() for item in roots_value)

    deps_value = data.get("dependencies", {})
    if not isinstance(deps_value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in deps_value.items()):
        raise RazError("dependencies must be an object mapping package names to paths", 1, 1, str(manifest))
    dependencies = {k: (root / v).resolve() for k, v in deps_value.items()}
    return PackageConfig(root, name, version, stdlib, source_roots, dependencies)


def discover_package_config(source: Path) -> PackageConfig:
    current = source.resolve().parent
    for directory in (current, *current.parents):
        manifest = directory / "raz.json"
        if manifest.exists():
            return load_package_config(manifest)
    # Backwards-compatible standalone source compilation.
    return PackageConfig(source.resolve().parent, source.resolve().parent.name or "raz-program", "0.0.0", None, (source.resolve().parent,), {})


def compile_file(path: Path, output: Path, package_manifest: Path | None = None) -> None:
    package = load_package_config(package_manifest) if package_manifest else discover_package_config(path)
    loader = ModuleLoader(package)
    root = loader.load(path)
    MacroExpander(root).expand()
    analyzer = Analyzer(root)
    analyzer.analyze()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(Codegen(root, analyzer).generate(), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="razc", description="Raz bootstrap compiler")
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--package", type=Path, help="path to a Raz package manifest (raz.json)")
    ns = ap.parse_args(argv)
    try:
        compile_file(ns.source, ns.output, ns.package)
    except (RazError, OSError, NotImplementedError) as exc:
        print(f"razc: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
