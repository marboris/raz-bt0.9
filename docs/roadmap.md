# Raz 2 Roadmap

Status legend: `[x]` implemented and verified, `[~]` partially implemented/prototyped, `[ ]` not implemented.

## Bootstrap compiler

- [x] M0.1 lexer, parser, AST spans, basic C++20 code generation
- [x] M0.2 recursive `.ro/.rt` modules, isolated scopes, qualified calls, diagnostics
- [x] M0.3 control flow, assignments, primitive types, lexical scopes, return analysis
- [x] M0.4 Core directives/macros and trusted native C++ escape hatches
- [x] M0.5 `async`, `await`, `sleep`, fire-and-forget future retention
- [x] M0.6 package manifest, project-local stdlib, source roots, local dependencies
- [x] M0.7 simple Java-like nominal type system: `int`, `long`, `float`, `double`, `bool`/`boolean`, `char`, `string`/`String`, `void`, strict widening-only assignment
- [x] M0.8 generic runtime collections: `List<T>`, `Map<K,V>`, `Set<T>`, literals, `new`, indexing, core methods
- [x] M0.9 module API decision: includes import the whole file and expose its functions; no private/export layer is introduced

## Post-M0 language work

- [ ] M0.10 diagnostics upgrade: error codes, notes, source snippets, recovery for multiple errors
- [ ] User-defined classes/records
- [ ] Enums and type aliases
- [ ] Generic/user-defined functions
- [ ] Pattern matching / richer control flow

## Runtime and concurrency

- [~] Current async backend: `std::async` + retained futures
- [ ] Replace/augment async backend with coroutine scheduler
- [ ] Optional worker/thread-pool backend inspired by the historical OpenHSL experiments
- [ ] Cancellation and structured concurrency
- [ ] Async IO primitives

## Package manager / reproducibility

- [x] Deterministic local package paths in `raz.json`
- [ ] Lockfile format (`raz.lock`)
- [ ] Package registry/index
- [ ] Remote dependency fetching and integrity checks
- [ ] Version range resolution and conflict handling

## Tooling

- [ ] Formatter (`razfmt`)
- [ ] Linter/static analyzer (`razlint`)
- [ ] Language server (LSP)
- [ ] Source maps / better generated-C++ correspondence
- [ ] Test runner for Raz projects

## Compiler evolution

- [ ] M1 native Raz compiler in C++
- [ ] Reusable compiler library/API
- [ ] Incremental compilation/cache
- [ ] Optional direct backend(s) beyond C++

## Historical ideas intentionally deferred

These appeared in the archived Raz/Marboris/OpenHSL/Horton sources but are not current language requirements:

- [ ] OpenMP-specific runtime backend
- [ ] libuv-specific task backend
- [ ] Taskflow backend
- [ ] HTTP server framework
- [ ] Telegram bot integration
- [ ] GPU/OpenCL experiments

They should only be promoted into the core language/runtime after the semantics are stable.
