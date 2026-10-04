# Raz 2 Architecture

## Pipeline

```text
Raz source (.ro/.rt)
        |
        v
      Lexer
        |
        v
      Parser
        |
        v
    AST + spans
        |
        v
   Macro / Core expansion
        |
        v
 Scope / semantic analysis
        |
        v
     C++20 codegen
        |
        v
 C++ compiler / linker
```

## Design rules

1. Language semantics belong in the compiler/core layer; platform-specific behavior is exposed through explicit `use` features.
2. `.ro` is reserved for core/meta declarations; `.rt` is normal application/runtime source.
3. Every include creates an explicit module/scope boundary.
4. Native C++ interop is provided through trusted `__eval` / `__phead` Core directives instead of teaching the bootstrap parser every C++ feature.
5. Runtime facilities (`async`, scheduler, IO, memory) remain separate from the front end.
6. The first compiler intentionally targets C++ rather than native machine code.
7. Macro expansion happens on the AST before semantic analysis so normal type/scope rules still apply to expanded code.
8. Async functions expose logical Raz return types while the generated C++ uses `std::future<T>`. Un-awaited standalone async calls are retained by the runtime until shutdown.

## Milestones

- M0.1: lexer/parser/scope/C++ codegen
- M0.2: imports/modules and diagnostics (implemented)
- M0.3: `if`, `while`, `for`, assignments, unary/comparison/logical operators, primitive type checking
- M0.4: Core methods/macros (implemented)
- M0.5: async/await runtime (implemented)
- M0.6: package/stdlib layout
- M1: native compiler implementation in C++

## M0.2 module model

- Source modules are resolved relative to the importing file.
- Both `.ro` and `.rt` are valid source-module extensions.
- Every included module is a distinct semantic scope.
- The filename stem is the module name in Raz and the generated C++ namespace.
- Calls across module boundaries use `module::function(...)`.
- A module may access only its direct imports; transitive imports are not re-exported.
- Cycles and duplicate/ambiguous module names are rejected.
- AST nodes retain source spans so diagnostics identify the originating file, line, and column.

## M0.4 Core model

- `__phead("...")` is a trusted root-level prelude escape hatch.
- `__eval("...")` is a trusted native C++ escape hatch usable inside function bodies.
- Macros are module-scope declarations and disappear before C++ code generation.
- Expression macros contain exactly one `return expression;`.
- Statement macros contain only expression statements and Core directives.
- Imported macros expand in the lexical context of their defining module for ordinary local function references.
- Recursive macro expansion is rejected.
