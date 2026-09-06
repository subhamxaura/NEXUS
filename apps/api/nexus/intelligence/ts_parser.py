"""TypeScript/JavaScript import extraction via regex (pragmatic V1).

Tree-sitter is deferred per the golden-path rule; this module resolves only
*relative* imports (`./x`, `../y`), which is all the dependency graph needs.
Bare package imports (`react`, `lodash`) are recorded as external names and
excluded from the graph. Complexity for TS/JS is a documented keyword
heuristic (see metrics.py), never presented as radon-grade.
"""

import os
import re
from dataclasses import dataclass

_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]|"""
    r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)|"""
    r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)|"""
    r"""export\s+[^'"]*?\s+from\s+['"]([^'"]+)['"])"""
)

_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")


@dataclass(frozen=True)
class TsFacts:
    imports: tuple[str, ...]
    exports_count: int


def parse_ts(source: str) -> TsFacts:
    imports: set[str] = set()
    for match in _IMPORT_RE.finditer(source):
        for group in match.groups():
            if group:
                imports.add(group)
    exports = len(re.findall(r"^\s*export\s+", source, re.MULTILINE))
    return TsFacts(imports=tuple(sorted(imports)), exports_count=exports)


def resolve_relative_import(src_path: str, spec: str, files: frozenset[str]) -> str | None:
    """Resolve a relative import spec to a repo-relative path, or None."""
    if not spec.startswith("."):
        return None
    base = os.path.normpath(os.path.join(os.path.dirname(src_path), spec)).replace(os.sep, "/")
    candidates = [base, *[base + ext for ext in _TS_EXTENSIONS]]
    for cand in candidates:
        if cand in files:
            return cand
    for index in (f"{base}/index.ts", f"{base}/index.tsx", f"{base}/index.js"):
        if index in files:
            return index
    return None
