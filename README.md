# Raz 2 — Bootstrap Compiler

Raz 2 is a clean restart based on the language/core ideas found in the archived Raz, Marboris, OpenHSL and Horton sources.

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

The compiler is intentionally written in Python for fast iteration. The generated target is standard C++20. Later milestones can replace the bootstrap implementation with a native Raz compiler.

## Run

```bash
python3 compiler/razc.py examples/hello.ro -o /tmp/hello.cpp
c++ -std=c++20 /tmp/hello.cpp -o /tmp/hello
/tmp/hello
```

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Modules (M0.2)

`include("path/to/module.ro");` loads a Raz source module relative to the importing file. Included modules compile into their own C++ namespace derived from the filename. Imported names are intentionally not injected into the caller's scope.

Example:

```raz
// lib/math.ro
function square(x: int) -> int {
    return x * x;
}

// main.ro
include("lib/math.ro");

function main() {
    echo(math::square(7));
}

main();
```

A module can only reference modules it directly includes. Cyclic includes are rejected before code generation.

Try the module example with `python3 compiler/razc.py examples/modules.ro -o /tmp/modules.cpp`.

## Packages and standard library (M0.6)

Raz packages can opt into a local manifest named `raz.json`. The compiler auto-discovers the nearest manifest above the source file, or a manifest can be passed explicitly with `--package`. Local package dependencies and a project-local standard library are resolved without network access:

```raz
include("std:math.ro");
include("pkg:demo/math.ro");

function main() {
    echo(std::math::square(7));
    echo(demo::math::triple(14));
}

main();
```

See `docs/m0.6.md` for the package manifest and resolution rules.

## Async (M0.5)

Raz supports asynchronous functions backed by generated C++20 futures:

```raz
async function double(x: int) -> int {
    sleep(1);
    return x * 2;
}

function main() {
    echo(await double(21));
}

main();
```

Standalone async calls are retained by the runtime until shutdown.

## M0.7–M0.9

Raz now uses a compact Java-like primitive type model with widening numeric conversions, aliases `boolean`/`String`, and character literals. It also supports `List<T>`, `Map<K,V>`, and `Set<T>` collections with literals, `new`, indexing, and a small method API.

Module visibility is intentionally simple: `include(...)` imports the entire file into its module namespace, and all declared functions are public. There is no private/export mechanism in M0.9.

See `docs/m0.7.md`, `docs/m0.8.md`, and `docs/m0.9.md`.

## Verification

The current bootstrap has 56 automated compiler tests covering modules, control flow, type checking, Core macros/directives, and async/await. The examples directory also has end-to-end C++20 compile/run coverage.
