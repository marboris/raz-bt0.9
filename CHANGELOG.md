# Changelog

## 0.2.0

- Added recursive `.ro`/`.rt` module loading.
- Added explicit module scopes and `module::function(...)` calls.
- Added dependency-ordered C++ namespace emission.
- Added cycle detection and module-name collision detection.
- Added source-aware diagnostics with file, line, and column.
- Added function arity and duplicate-parameter validation.
- Added return-type inference for generated C++ functions where the return expression has a concrete basic type.
- Added nested-module integration tests.

## M0.3

- Added `if/else`, `while`, and C-style `for`.
- Added assignments and lexical block scopes with shadowing.
- Added unary, comparison, and logical operators.
- Added primitive type annotations and static type validation.
- Added control-flow and type-system regression/integration coverage.


## M0.4

- Added `__phead("...")` Core prelude directives with duplicate suppression.
- Added `__eval("...")` trusted native C++ escape hatch with function-body support.
- Added AST-level expression and statement macros.
- Added imported module macro expansion with defining-module function qualification.
- Added macro arity, recursion, name-collision, and body-shape diagnostics.
- Added Core/macro examples and integration coverage.


## M0.5

- Added `async function` declarations backed by generated `std::future<T>`.
- Added `await` expressions that unwrap async tasks and can be used from any function, including `main`.
- Added implicit fire-and-forget retention for standalone async calls through `raz::AsyncRegistry` and `raz::spawn`.
- Added the `sleep(int)` runtime helper.
- Added async module support and future-variable awaiting.
- Added async/future type diagnostics and rejection of `async main`.
- Added end-to-end async C++ compilation/execution coverage.


## M0.6

- Added `raz.json` package manifests with name/version/source roots/stdlib/dependencies.
- Added manifest auto-discovery and explicit `--package` selection.
- Added `std:` includes for the project-local standard library.
- Added `pkg:` includes for local package dependencies.
- Added `src:` includes for package source roots.
- Added package-qualified module names such as `demo::math::triple(...)` and `std::math::square(...)`.
- Generalized qualified-call parsing, macro resolution, semantic resolution, and C++ namespace emission beyond two segments.
- Added the first checked-in stdlib module and package integration fixtures.
- Kept dependency acquisition local and deterministic; network package fetching is intentionally deferred.


## v0.9 — M0.7–M0.9

- Added Java-like primitive type semantics and strict widening-only numeric assignment.
- Added `List<T>`, `Map<K,V>`, and `Set<T>` with C++ STL code generation, literals, indexing, and common methods.
- Added `char`, `boolean`, and `String` source-level support.
- Closed M0.9 with the existing whole-file include/public-by-default module model; no visibility layer is added.
