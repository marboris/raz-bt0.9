import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
RAZC = ROOT / "compiler" / "razc.py"
class CompilerTests(unittest.TestCase):
    def compile(self, source: str, *, extra_files: dict[str, str] | None = None, run_cpp: bool = False) -> tuple[str, str | None]:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            src = base / "x.ro"
            out = base / "x.cpp"
            src.write_text(source, encoding="utf-8")
            for name, content in (extra_files or {}).items():
                p = base / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            r = subprocess.run([sys.executable, str(RAZC), str(src), "-o", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            cpp = out.read_text(encoding="utf-8")
            if not run_cpp:
                return cpp, None
            exe = base / "app"
            c = subprocess.run(["c++", "-std=c++20", str(out), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(c.returncode, 0, c.stderr)
            rr = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(rr.returncode, 0, rr.stderr)
            return cpp, rr.stdout
    def run_error(self, source: str, *, extra_files: dict[str, str] | None = None) -> str:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            src = base / "x.ro"
            out = base / "x.cpp"
            src.write_text(source, encoding="utf-8")
            for name, content in (extra_files or {}).items():
                p = base / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            r = subprocess.run([sys.executable, str(RAZC), str(src), "-o", str(out)], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            return r.stderr
    def test_hello(self):
        cpp, _ = self.compile('function main() { let x = 6 * 7; echo(x); }\nmain();\n')
        self.assertIn('auto x = (6 * 7);', cpp)
        self.assertIn('raz::echo(x);', cpp)
    def test_strings_and_bools(self):
        cpp, _ = self.compile('function main() { let x = "a" + "b"; let ok = true; echo(x); echo(ok); }\nmain();\n')
        self.assertIn('auto x = (std::string("a") + std::string("b"));', cpp)
        self.assertIn('auto ok = true;', cpp)
    def test_control_flow(self):
        source = '''
function main() {
    let total: int = 0;
    let i: int = 0;
    while (i < 3) {
        total = total + i;
        i = i + 1;
    }
    for (let j: int = 0; j < 3; j = j + 1) {
        total = total + 1;
    }
    if (total == 6) {
        echo("ok");
    } else if (total > 6) {
        echo("high");
    } else {
        echo("low");
    }
}
main();
'''
        cpp, stdout = self.compile(source, run_cpp=True)
        self.assertIn('while ((i < 3))', cpp)
        self.assertIn('for (int j = 0; (j < 3); j = (j + 1))', cpp)
        self.assertIn('else if ((total > 6))', cpp)
        self.assertEqual(stdout, 'ok\n')
    def test_unary_and_comparison(self):
        cpp, stdout = self.compile('function main() { let x: int = -3; let y: bool = !false; if (y && x < 0) { echo(x); } }\nmain();\n', run_cpp=True)
        self.assertIn('int x = (-3);', cpp)
        self.assertIn('bool y = (!false);', cpp)
        self.assertEqual(stdout, '-3\n')
    def test_explicit_function_types(self):
        cpp, stdout = self.compile('function add(a: int, b: double) -> double { return a + b; } function main() { let x: double = add(2, 3.5); echo(x); }\nmain();\n', run_cpp=True)
        self.assertIn('double add(int a, double b)', cpp)
        self.assertEqual(stdout, '5.5\n')
    def test_scope_shadowing(self):
        cpp, stdout = self.compile('function main() { let x = 1; if (true) { let x = 2; echo(x); } echo(x); }\nmain();\n', run_cpp=True)
        self.assertEqual(stdout, '2\n1\n')
    def test_missing_return_path(self):
        err = self.run_error('function value(x: bool) -> int { if (x) { return 1; } } function main() { echo(value(true)); }\nmain();\n')
        self.assertIn('may finish without returning int', err)
    def test_main_signature(self):
        err = self.run_error('function main() -> void {}\nmain();\n')
        self.assertIn('function main() must return int', err)
    def test_type_error(self):
        err = self.run_error('function main() { let x: int = "bad"; }\nmain();\n')
        self.assertIn('cannot assign std::string to int', err)
        self.assertIn('x.ro:1:', err)
    def test_bad_condition(self):
        err = self.run_error('function main() { if (1) { echo("x"); } }\nmain();\n')
        self.assertIn('if condition must be bool', err)
    def test_unknown_name(self):
        err = self.run_error('function main() { echo(missing); }\nmain();\n')
        self.assertIn('unknown name missing', err)
        self.assertIn('x.ro:1:', err)
    def test_include_isolated_namespace(self):
        cpp, stdout = self.compile(
            'include("lib.ro");\nfunction main() { let x = lib::value(); echo(x); }\nmain();\n',
            extra_files={"lib.ro": 'function value() { return 42; }\n'},
            run_cpp=True,
        )
        self.assertIn("namespace lib {", cpp)
        self.assertIn("lib::value()", cpp)
        self.assertEqual(stdout, "42\n")
    def test_non_direct_module_is_rejected(self):
        err = self.run_error(
            'include("a.ro");\nfunction main() { echo(b::value()); }\nmain();\n',
            extra_files={
                "a.ro": 'include("b.ro");\nfunction relay() { b::value(); }\n',
                "b.ro": 'function value() { return 7; }\n',
            },
        )
        self.assertIn("module b is not directly included", err)
    def test_include_cycle(self):
        err = self.run_error(
            'include("a.ro");\nfunction main() {}\nmain();\n',
            extra_files={"a.ro": 'include("x.ro");\n', "x.ro": 'include("a.ro");\n'},
        )
        self.assertIn("cyclic include detected", err)
    def test_nested_include_visibility_and_dependency_order(self):
        cpp, stdout = self.compile(
            'include("lib.ro");\nfunction main() { echo(lib::answer()); }\nmain();\n',
            extra_files={
                "lib.ro": 'include("nested/value.ro");\nfunction answer() { return value::number(); }\n',
                "nested/value.ro": 'function number() { return 21 * 2; }\n',
            },
            run_cpp=True,
        )
        self.assertIn("namespace value {", cpp)
        self.assertIn("namespace lib {", cpp)
        self.assertIn("value::number()", cpp)
        self.assertEqual(stdout, "42\n")
    def test_module_name_collision(self):
        err = self.run_error(
            'include("a/math.ro");\ninclude("b/math.ro");\nfunction main() {}\nmain();\n',
            extra_files={
                "a/math.ro": 'function a() {}\n',
                "b/math.ro": 'function b() {}\n',
            },
        )
        self.assertIn("module name math is ambiguous", err)
    def test_missing_include(self):
        err = self.run_error('include("missing.ro");\nfunction main() {}\nmain();\n')
        self.assertIn("source file not found", err)
        self.assertIn("missing.ro:1:1", err)
    def test_comments_and_empty_for_parts(self):
        cpp, stdout = self.compile(
            '/* block */\nfunction main() { let i = 0; for (; i < 2; ) { echo(i); i = i + 1; } // end\n}\nmain();\n',
            run_cpp=True,
        )
        self.assertIn('for (; (i < 2); )', cpp)
        self.assertEqual(stdout, '0\n1\n')
# M0.4 Core methods/macros
    def test_expression_macro(self):
        cpp, stdout = self.compile(
            'macro twice(x) { return x + x; }\nfunction main() { let y: int = twice(21); echo(y); }\nmain();\n',
            run_cpp=True,
        )
        self.assertNotIn('macro', cpp)
        self.assertIn('int y = (21 + 21);', cpp)
        self.assertEqual(stdout, '42\n')
    def test_statement_macro(self):
        cpp, stdout = self.compile(
            'macro say(x) { echo(x); echo(x); }\nfunction main() { say("Hi"); }\nmain();\n',
            run_cpp=True,
        )
        self.assertEqual(stdout, 'Hi\nHi\n')
        self.assertNotIn('say(', cpp)
    def test_nested_macro_expansion(self):
        cpp, stdout = self.compile(
            'macro inc(x) { return x + 1; }\nmacro twice_inc(x) { return inc(inc(x)); }\nfunction main() { echo(twice_inc(40)); }\nmain();\n',
            run_cpp=True,
        )
        self.assertEqual(stdout, '42\n')
    def test_module_macro_and_definition_context(self):
        cpp, stdout = self.compile(
            'include("lib/core.ro");\nfunction main() { echo(core::double_value(21)); }\nmain();\n',
            extra_files={
                'lib/core.ro': 'function helper(x: int) -> int { return x; }\nmacro double_value(x) { return helper(x) + helper(x); }\n',
            },
            run_cpp=True,
        )
        self.assertIn('core::helper', cpp)
        self.assertEqual(stdout, '42\n')
    def test_macro_arity_error(self):
        err = self.run_error('macro twice(x) { return x + x; }\nfunction main() { echo(twice(1, 2)); }\nmain();\n')
        self.assertIn('wrong number of arguments for macro twice', err)
    def test_macro_recursion_error(self):
        err = self.run_error('macro a(x) { return b(x); }\nmacro b(x) { return a(x); }\nfunction main() { echo(a(1)); }\nmain();\n')
        self.assertIn('cyclic macro expansion detected', err)
    def test_macro_function_name_collision(self):
        err = self.run_error('macro same(x) { return x; }\nfunction same() {}\nfunction main() {}\nmain();\n')
        self.assertIn('declared as both function and macro', err)
    def test_statement_macro_restriction(self):
        err = self.run_error('macro bad(x) { let y = x; echo(y); }\nfunction main() { bad(1); }\nmain();\n')
        self.assertIn('statement macro bad may only contain expression statements or Core directives', err)
    def test_top_level_macro_invocation_rejected(self):
        err = self.run_error('macro say(x) { echo(x); }\nsay("hello");\nfunction main() {}\nmain();\n')
        self.assertIn('macro invocation say is only allowed inside a function', err)
    def test_core_phead_and_eval(self):
        cpp, stdout = self.compile(
            '__phead("#include <iomanip>");\n__phead("#include <iomanip>");\nfunction main() { __eval("std::cout << 3.50 << std::endl;"); }\nmain();\n',
            run_cpp=True,
        )
        self.assertEqual(cpp.count('#include <iomanip>'), 1)
        self.assertEqual(stdout, '3.5\n')
    def test_core_eval_inside_module_function(self):
        cpp, stdout = self.compile(
            'include("lib.ro");\nfunction main() { lib::run(); }\nmain();\n',
            extra_files={
                'lib.ro': 'function run() { __eval("std::cout << 42 << std::endl;"); }\n',
            },
            run_cpp=True,
        )
        self.assertEqual(stdout, '42\n')
    def test_top_level_module_eval_rejected(self):
        err = self.run_error(
            'include("lib.ro");\nfunction main() {}\nmain();\n',
            extra_files={'lib.ro': '__eval("int x = 1;");\nfunction run() {}\n'},
        )
        self.assertIn('top-level __eval is only allowed in the root source file', err)
    def test_phead_inside_function_rejected(self):
        err = self.run_error('function main() { __phead("#include <vector>"); }\nmain();\n')
        self.assertIn('__phead is only valid at module scope', err)
    def test_top_level_module_phead_rejected(self):
        err = self.run_error(
            'include("lib.ro");\nfunction main() {}\nmain();\n',
            extra_files={'lib.ro': '__phead("#include <vector>");\nfunction run() {}\n'},
        )
        self.assertIn('top-level __phead is only allowed in the root source file', err)
    def test_async_await_and_future_variable(self):
        cpp, stdout = self.compile(
            'async function double_value(x: int) -> int { return x * 2; }\n'
            'function main() { let task = double_value(21); echo(await task); echo(await double_value(10)); }\n'
            'main();\n',
            run_cpp=True,
        )
        self.assertIn('std::future<int> double_value(int x)', cpp)
        self.assertIn('std::async(std::launch::async', cpp)
        self.assertIn('.get()', cpp)
        self.assertEqual(stdout, '42\n20\n')
    def test_async_fire_and_forget_is_retained(self):
        cpp, stdout = self.compile(
            'async function announce() { echo(42); }\n'
            'function main() { announce(); }\n'
            'main();\n',
            run_cpp=True,
        )
        self.assertIn('raz::spawn(announce());', cpp)
        self.assertEqual(stdout, '42\n')
    def test_await_requires_future(self):
        err = self.run_error('function main() { echo(await 42); }\nmain();\n')
        self.assertIn('await requires an async task/future', err)
    def test_async_main_rejected(self):
        err = self.run_error('async function main() {}\nmain();\n')
        self.assertIn('function main() cannot be async', err)
    def test_sleep_builtin_typecheck(self):
        cpp, stdout = self.compile('function main() { sleep(0); echo(7); }\nmain();\n', run_cpp=True)
        self.assertIn('raz::sleep(0);', cpp)
        self.assertEqual(stdout, '7\n')
    def test_async_module(self):
        cpp, stdout = self.compile(
            'include("lib.ro");\nfunction main() { echo(await lib::work(21)); }\nmain();\n',
            extra_files={'lib.ro': 'async function work(x: int) -> int { return x * 2; }\n'},
            run_cpp=True,
        )
        self.assertIn('std::future<int> work(int x)', cpp)
        self.assertEqual(stdout, '42\n')
    def test_echo_future_rejected(self):
        err = self.run_error('async function work() -> int { return 1; } function main() { echo(work()); }\nmain();\n')
        self.assertIn('cannot echo an async task; use await', err)
    # M0.6 package / stdlib
    def test_project_stdlib_include(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "stdlib").mkdir()
            (base / "stdlib" / "math.ro").write_text(
                'function square(x: int) -> int { return x * x; }\n', encoding="utf-8"
            )
            (base / "raz.json").write_text(
                '{"name":"app","version":"0.1.0","stdlib":"stdlib","source_roots":["src"],"dependencies":{}}',
                encoding="utf-8",
            )
            src = base / "main.ro"
            out = base / "main.cpp"
            src.write_text(
                'include("std:math.ro");\nfunction main() { echo(std::math::square(7)); }\nmain();\n',
                encoding="utf-8",
            )
            r = subprocess.run([sys.executable, str(RAZC), str(src), "-o", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            cpp = out.read_text(encoding="utf-8")
            self.assertIn("namespace std::math {", cpp)
            self.assertIn("std::math::square(7)", cpp)
    def test_local_source_root_include(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "src").mkdir()
            (base / "src" / "tool.ro").write_text('function value() -> int { return 9; }\n', encoding="utf-8")
            (base / "raz.json").write_text(
                '{"name":"app","version":"0.1.0","stdlib":"stdlib","source_roots":["src"],"dependencies":{}}',
                encoding="utf-8",
            )
            src = base / "main.ro"
            out = base / "main.cpp"
            src.write_text('include("src:tool.ro");\nfunction main() { echo(tool::value()); }\nmain();\n', encoding="utf-8")
            r = subprocess.run([sys.executable, str(RAZC), str(src), "-o", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
    def test_local_package_dependency(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            dep = base / "demo"
            (dep / "src").mkdir(parents=True)
            (dep / "src" / "math.ro").write_text('function triple(x: int) -> int { return x * 3; }\n', encoding="utf-8")
            (dep / "raz.json").write_text(
                '{"name":"demo","version":"0.1.0","source_roots":["src"],"dependencies":{}}', encoding="utf-8"
            )
            app = base / "app"
            app.mkdir()
            (app / "raz.json").write_text(
                '{"name":"app","version":"0.1.0","source_roots":["src"],"dependencies":{"demo":"../demo"}}', encoding="utf-8"
            )
            src = app / "main.ro"
            out = app / "main.cpp"
            src.write_text('include("pkg:demo/math.ro");\nfunction main() { echo(demo::math::triple(14)); }\nmain();\n', encoding="utf-8")
            r = subprocess.run([sys.executable, str(RAZC), str(src), "-o", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            cpp = out.read_text(encoding="utf-8")
            self.assertIn("namespace demo::math {", cpp)
            exe = app / "app"
            c = subprocess.run(["c++", "-std=c++20", str(out), "-o", str(exe)], capture_output=True, text=True)
            self.assertEqual(c.returncode, 0, c.stderr)
            rr = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(rr.stdout, "42\n")
    def test_missing_dependency(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "raz.json").write_text(
                '{"name":"app","version":"0.1.0","dependencies":{}}', encoding="utf-8"
            )
            err = self.run_error('include("pkg:missing/core.ro");\nfunction main() {}\nmain();\n')
            self.assertIn("unknown package dependency missing", err)
    def test_explicit_package_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = base / "raz.json"
            manifest.write_text('{"name":"explicit","version":"1.2.3","stdlib":"stdlib","source_roots":["src"],"dependencies":{}}', encoding="utf-8")
            (base / "src").mkdir()
            src = base / "elsewhere" / "main.ro"
            src.parent.mkdir()
            src.write_text('function main() { echo(3); }\nmain();\n', encoding="utf-8")
            out = base / "main.cpp"
            r = subprocess.run([sys.executable, str(RAZC), str(src), "-o", str(out), "--package", str(manifest)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("int main()", out.read_text(encoding="utf-8"))
    def test_stdlib_missing_is_diagnostic(self):
        err = self.run_error('include("std:math.ro");\nfunction main() {}\nmain();\n')
        self.assertIn("standard library is not configured for this package", err)
    # M0.7 simple Java-like nominal type system
    def test_m07_java_like_primitive_types_and_aliases(self):
        cpp, stdout = self.compile(
            """function main() {
                let a: int = 10;
                let b: long = a;
                let c: float = b;
                let d: double = c;
                let ch: char = 'A';
                let ok: boolean = true;
                let s: String = \"Raz\";
                if (ok && ch < 100) { echo(s); }
            }
            main();
            """,
            run_cpp=True,
        )
        self.assertIn("long long b = a;", cpp)
        self.assertIn("float c = b;", cpp)
        self.assertIn("char ch = 'A';", cpp)
        self.assertIn("bool ok = true;", cpp)
        self.assertIn("std::string s = std::string(\"Raz\");", cpp)
        self.assertEqual(stdout, "Raz\n")
    def test_m07_float_literal_suffix(self):
        cpp, stdout = self.compile("function main() { let x: float = 1.5f; echo(x); }\nmain();\n", run_cpp=True)
        self.assertIn("float x = 1.5;", cpp)
        self.assertEqual(stdout, "1.5\n")

    def test_m07_numeric_widening_and_no_narrowing(self):
        cpp, stdout = self.compile(
            "function main() { let x: double = 1 + 2.5; echo(x); }\nmain();\n",
            run_cpp=True,
        )
        self.assertIn("double x = (1 + 2.5);", cpp)
        self.assertEqual(stdout, "3.5\n")
        err = self.run_error("function main() { let x: int = 2.5; }\nmain();\n")
        self.assertIn("cannot assign double to int", err)
    def test_m07_unknown_and_void_variable_type_errors(self):
        err = self.run_error("function main() { let x: Nope = 1; }\nmain();\n")
        self.assertIn("unknown type Nope", err)
        err = self.run_error("function main() { let x: void = 0; }\nmain();\n")
        self.assertIn("void is not allowed here", err)
    # M0.8 collections
    def test_m08_list_literal_and_methods(self):
        cpp, stdout = self.compile(
            """function main() {
                let xs: List<int> = [1, 2, 3];
                xs.add(4);
                echo(xs.get(2));
                echo(xs.size());
                echo(xs.contains(4));
                echo(xs[1]);
            }
            main();
            """,
            run_cpp=True,
        )
        self.assertIn("std::vector<int> xs", cpp)
        self.assertIn("xs.push_back(4)", cpp)
        self.assertIn("xs[2]", cpp)
        self.assertEqual(stdout, "3\n4\n1\n2\n")
    def test_m08_empty_list_constructor(self):
        cpp, stdout = self.compile(
            """function main() {
                let names: List<String> = new List<String>();
                names.add("A");
                names.add("B");
                echo(names.get(1));
            }
            main();
            """,
            run_cpp=True,
        )
        self.assertIn("std::vector<std::string> names = std::vector<std::string>{};", cpp)
        self.assertEqual(stdout, "B\n")
    def test_m08_map_methods_and_indexing(self):
        cpp, stdout = self.compile(
            """function main() {
                let prices: Map<String, double> = {\"cpu\": 3.5, \"ram\": 4.0};
                prices.put(\"gpu\", 5);
                echo(prices.get(\"gpu\"));
                echo(prices.contains(\"cpu\"));
                echo(prices[\"ram\"]);
                echo(prices.size());
            }
            main();
            """,
            run_cpp=True,
        )
        self.assertIn("std::map<std::string, double> prices", cpp)
        self.assertIn('prices[std::string("gpu")] = 5', cpp)
        self.assertEqual(stdout, "5\n1\n4\n3\n")
    def test_m08_set_methods_and_literal(self):
        cpp, stdout = self.compile(
            """function main() {
                let tags: Set<int> = new Set<int>();
                tags.add(10);
                tags.add(20);
                echo(tags.contains(10));
                tags.remove(10);
                echo(tags.size());
                let nums: Set<int> = [1, 2, 3];
                echo(nums.contains(2));
            }
            main();
            """,
            run_cpp=True,
        )
        self.assertIn("std::set<int> tags", cpp)
        self.assertIn("tags.insert(10)", cpp)
        self.assertIn("tags.erase(10)", cpp)
        self.assertEqual(stdout, "1\n1\n1\n")
    def test_m08_collection_type_errors(self):
        err = self.run_error(
            "function main() { let xs: List<int> = [1]; xs.add(\"bad\"); }\nmain();\n"
        )
        self.assertIn("cannot assign std::string to int", err)
        err = self.run_error(
            "function main() { let xs: List<int> = [1]; echo(xs.get(\"bad\")); }\nmain();\n"
        )
        self.assertIn("collection index must be int", err)
    def test_m08_empty_collection_requires_type(self):
        err = self.run_error("function main() { let xs = []; }\nmain();\n")
        self.assertIn("empty collection literal requires an explicit List<T> or Set<T> type", err)
    def test_m09_include_is_public_by_design(self):
        cpp, stdout = self.compile(
            'include("lib.ro");\nfunction main() { echo(lib::visible()); }\nmain();\n',
            extra_files={"lib.ro": "function visible() -> int { return 42; }\n"},
            run_cpp=True,
        )
        self.assertIn("lib::visible()", cpp)
        self.assertEqual(stdout, "42\n")
if __name__ == "__main__":
    unittest.main()
