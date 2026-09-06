"""Python parsing via stdlib `ast`: imports, symbols, insecure patterns.

Complexity/MI come from radon (see metrics.py); this module extracts structure.
"""

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class InsecureHit:
    line: int
    rule_id: str
    message: str


@dataclass(frozen=True)
class PythonFacts:
    imports: tuple[str, ...]
    functions: tuple[str, ...]
    classes: tuple[str, ...]
    insecure: tuple[InsecureHit, ...]
    parse_error: str | None = None


_INSECURE_CALLS: dict[str, tuple[str, str]] = {
    "eval": ("py-eval-exec", "use of eval() allows arbitrary code execution"),
    "exec": ("py-eval-exec", "use of exec() allows arbitrary code execution"),
    "pickle.loads": ("py-pickle", "pickle.loads on untrusted data allows code execution"),
    "pickle.load": ("py-pickle", "pickle.load on untrusted data allows code execution"),
    "yaml.load": ("py-yaml-load", "yaml.load without SafeLoader allows code execution"),
    "os.system": ("py-os-system", "os.system invokes a shell; prefer subprocess without shell"),
}


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    cur: ast.AST | None = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports: list[str] = []
        self.functions: list[str] = []
        self.classes: list[str] = []
        self.insecure: list[InsecureHit] = []

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.imports.append(a.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imports.append((".".join([""] * node.level) if node.level else "") + node.module)
        elif node.level:
            self.imports.append("." * node.level)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted(node.func)
        short = name.split(".")[-1] if name else ""
        for candidate in (name, short):
            if candidate in _INSECURE_CALLS:
                rule_id, message = _INSECURE_CALLS[candidate]
                self.insecure.append(InsecureHit(node.lineno, rule_id, message))
                break
        if name.endswith("subprocess.Popen") or name == "Popen":
            for kw in node.keywords:
                if (
                    kw.arg == "shell"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    self.insecure.append(
                        InsecureHit(
                            node.lineno,
                            "py-subprocess-shell",
                            "subprocess with shell=True allows shell injection",
                        )
                    )
        elif name == "call" or name.endswith("subprocess.call"):
            for kw in node.keywords:
                if (
                    kw.arg == "shell"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    self.insecure.append(
                        InsecureHit(
                            node.lineno,
                            "py-subprocess-shell",
                            "subprocess with shell=True allows shell injection",
                        )
                    )
        self.generic_visit(node)


def parse_python(source: str) -> PythonFacts:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return PythonFacts(
            imports=(),
            functions=(),
            classes=(),
            insecure=(),
            parse_error=f"syntax error at line {e.lineno}: {e.msg}",
        )
    visitor = _Visitor()
    visitor.visit(tree)
    return PythonFacts(
        imports=tuple(sorted(set(visitor.imports))),
        functions=tuple(visitor.functions),
        classes=tuple(visitor.classes),
        insecure=tuple(visitor.insecure),
    )


# Re-exported for a stable interface if tree-sitter lands later.
__all__ = ["InsecureHit", "PythonFacts", "parse_python"]
