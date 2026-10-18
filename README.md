# Raz 2 — Bootstrap Compiler

Milestones 0.1 through 0.4 implement a small source-to-C++ pipeline with modules, control flow, primitive type checking, and AST-level Core macros/directives:

- `use linux;`
- `include("file.ro");`
- `function name(...) { ... }`
- optional typed functions: `function add(a: int) -> int { ... }`
- `let name = expression;` and typed lets: `let name: int = expression;`
- `return expression;`
- `echo(expression);`
- function calls
- integer, floating-point, character, string, boolean and arithmetic expressions
- `if / else`, `while`, and C-style `for`
- unary and comparison/logical operators
- assignments and primitive type checking
- lexical scopes for functions/blocks
- recursive `.ro`/`.rt` module loading
- module-local C++ namespaces and qualified calls such as `math::square(7)`
- cyclic include detection and module-name collision detection
- source-aware diagnostics (`file:line:column`)
- Core directives `__phead(...)` and `__eval(...)`
- AST-level expression and statement macros, including imported module macros
- `async function`, `await`, async-task retention, and `sleep(...)` runtime support
- recursive macro expansion detection and macro arity/name diagnostics
