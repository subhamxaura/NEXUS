"""Deterministic C/C++ heuristic analysis (V1).

No compiler-grade AST: comments/strings are masked line-wise (line numbers
preserved), then regexes extract #includes, function definitions, branch
keywords, and conservative dangerous-pattern hits. Designed to never raise on
malformed input — worst case is fewer facts, never a crashed analysis.

`.h` files are analyzed with the same heuristics; the C vs C++ label only
affects display and finding thresholds, not the parsing method.
"""

import os
import re
from dataclasses import dataclass

from nexus.intelligence.python_parser import InsecureHit

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*([<"])([^">]+)[">]')
_FUNC_RE = re.compile(
    r"""^\s*
    (?:(?:static|inline|extern|virtual|explicit|constexpr|const|unsigned|signed|long|short|volatile|register)\s+)*
    (?:struct\s+\w+\s*\*?|union\s+\w+\s*\*?|enum\s+\w+|[\w:]+(?:\s*[*&]+\s*|\s+))
    (\w+)\s*\([^;{}]*\)\s*
    (?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:final\s*)?\{\s*$""",
    re.VERBOSE,
)
# Same signature shape but ending at `)` (Allman style: `{` on the next line).
_FUNC_SIG_RE = re.compile(
    r"""^\s*
    (?:(?:static|inline|extern|virtual|explicit|constexpr|const|unsigned|signed|long|short|volatile|register)\s+)*
    (?:struct\s+\w+\s*\*?|union\s+\w+\s*\*?|enum\s+\w+|[\w:]+(?:\s*[*&]+\s*|\s+))
    (\w+)\s*\([^;{}]*\)\s*
    (?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:final\s*)?$""",
    re.VERBOSE,
)
_BRANCH_RE = re.compile(r"\b(if|for|while|case|catch|switch)\b|&&|\|\||\?(?![?.:])")
_KEYWORD_NAMES = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "return",
        "sizeof",
        "typeof",
        "alignof",
        "noexcept",
        "requires",
        "static_assert",
    }
)

# Conservative dangerous-call rules: (pattern, rule_id, message, severity-hit-kind).
# Severity mapping lives in pipeline.py; rule_ids here must stay in sync.
_CALL_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"\bgets\s*\("),
        "c-gets",
        "gets() cannot be used safely; it has no bounds checking",
    ),
    (
        re.compile(r"\bstrcpy\s*\("),
        "c-strcpy",
        "strcpy() is unbounded; prefer a bounded copy with explicit size",
    ),
    (
        re.compile(r"\bstrcat\s*\("),
        "c-strcat",
        "strcat() is unbounded; track remaining buffer capacity",
    ),
    (
        re.compile(r"\bsprintf\s*\("),
        "c-sprintf",
        "sprintf() is unbounded; prefer snprintf with explicit size",
    ),
    (
        re.compile(r"\bsystem\s*\("),
        "c-system",
        "system() invokes a shell; avoid with variable input",
    ),
    (re.compile(r"\bpopen\s*\("), "c-popen", "popen() invokes a shell; avoid with variable input"),
)
_SCANF_RE = re.compile(r'\b([a-z]*scanf)\s*\(\s*"([^"]*)"')
_UNBOUNDED_S_RE = re.compile(r"%(?!(\d+))[^%]*?[s\[]")
_ALLOC_RE = re.compile(r"\b(malloc|calloc|realloc)\s*\(")
_FREE_RE = re.compile(r"\bfree\s*\(")

_C_EXTENSIONS = (".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx")


@dataclass(frozen=True)
class CFacts:
    includes: tuple[str, ...]
    functions: tuple[str, ...]
    insecure: tuple[InsecureHit, ...]
    parse_error: str | None = None


def _mask_line(line: str, in_block: bool) -> tuple[str, bool]:
    """Replace comments/strings with spaces, preserving length and newlines."""
    out: list[str] = []
    i = 0
    n = len(line)
    quote: str | None = None
    while i < n:
        ch = line[i]
        nxt = line[i + 1] if i + 1 < n else ""
        if in_block:
            if ch == "*" and nxt == "/":
                out.extend([" ", " "])
                i += 2
                in_block = False
            else:
                out.append(" " if ch != "\n" else "\n")
                i += 1
        elif quote is not None:
            if ch == "\\":
                out.extend([" ", " "] if nxt else [" "])
                i += 2 if nxt else 1
            elif ch == quote:
                out.append(" ")
                quote = None
                i += 1
            else:
                out.append(" " if ch != "\n" else "\n")
                i += 1
        elif ch == "/" and nxt == "/":
            out.extend([" "] * (n - i))
            break
        elif ch == "/" and nxt == "*":
            out.extend([" ", " "])
            i += 2
            in_block = True
        elif ch in ("'", '"'):
            out.append(" ")
            quote = ch
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out), in_block


def _masked_lines(source: str) -> list[str]:
    masked: list[str] = []
    in_block = False
    for line in source.splitlines():
        text, in_block = _mask_line(line, in_block)
        masked.append(text)
    return masked


def parse_c(source: str) -> CFacts:
    masked = _masked_lines(source)
    includes: list[str] = []
    functions: list[str] = []
    insecure: list[InsecureHit] = []
    raw_lines = source.splitlines()
    alloc_first_line: int | None = None
    alloc_count = 0
    free_count = 0
    total_lines = len(raw_lines)
    for lineno, (raw, code) in enumerate(zip(raw_lines, masked, strict=True), start=1):
        # NOTE: includes are read from the raw line because the masker turns
        # quoted paths into spaces. Comment lines are skipped; a phantom spec
        # is harmless since resolution requires the target file to exist.
        stripped = raw.strip()
        if not stripped.startswith(("//", "*", "/*")):
            inc = _INCLUDE_RE.match(raw)
            if inc and inc.group(1) == '"':
                includes.append(inc.group(2).strip())
        func = _FUNC_RE.match(code)
        name: str | None = None
        if func:
            name = func.group(1)
        else:
            sig = _FUNC_SIG_RE.match(code)
            if sig:
                # Allman style: accept only if the next non-blank line opens a block.
                nxt = lineno
                while nxt < total_lines and not masked[nxt].strip():
                    nxt += 1
                if nxt < total_lines and masked[nxt].lstrip().startswith("{"):
                    name = sig.group(1)
        if name is not None and name not in _KEYWORD_NAMES:
            functions.append(name)
        for pattern, rule_id, message in _CALL_RULES:
            if pattern.search(code):
                insecure.append(InsecureHit(lineno, rule_id, message))
        # The format string only exists in the raw text, so scan raw lines —
        # but each hit's call-site keyword must also appear verbatim at the
        # same offset in the masked line: the masker blanks comments and
        # string contents, so a surviving keyword proves the call site is
        # executable code, not a commented-out line or a string mentioning
        # scanf. Checking every match also fixes the same-line blind spot
        # where a bounded scanf hid an unbounded one from .search().
        for scanf in _SCANF_RE.finditer(raw):
            keyword = scanf.group(1)
            if code[scanf.start() : scanf.start() + len(keyword)] != keyword:
                continue
            if _UNBOUNDED_S_RE.search(scanf.group(2)):
                insecure.append(
                    InsecureHit(
                        lineno,
                        "c-scanf-unbounded",
                        f"{scanf.group(1)}() with unbounded %s; add an explicit field width",
                    )
                )
        if _ALLOC_RE.search(code):
            alloc_count += 1
            if alloc_first_line is None:
                alloc_first_line = lineno
        free_count += len(_FREE_RE.findall(code))
    if alloc_count > 0 and free_count == 0 and alloc_first_line is not None:
        insecure.append(
            InsecureHit(
                alloc_first_line,
                "c-missing-free",
                f"{alloc_count} malloc/calloc/realloc call(s) with no free() in this file; "
                "verify ownership and lifetime",
            )
        )
    return CFacts(
        includes=tuple(sorted(set(includes))),
        functions=tuple(functions),
        insecure=tuple(insecure),
    )


def c_branch_count(source: str) -> int:
    """Branch keywords over masked code (comments/strings excluded)."""
    return sum(len(_BRANCH_RE.findall(line)) for line in _masked_lines(source))


def resolve_c_include(src_path: str, spec: str, files: frozenset[str]) -> str | None:
    """Resolve a quoted local #include to a repo-relative path, or None.

    Only quoted includes resolve (angle includes are system headers).
    Candidates: same directory as the includer, then repo root. A bare
    basename without extension also tries common header extensions.
    """
    if not spec or spec.startswith("<") or ".." in spec.split("/"):
        return None
    if spec.startswith("/"):
        return None
    candidates = [
        os.path.normpath(os.path.join(os.path.dirname(src_path), spec)).replace(os.sep, "/"),
        os.path.normpath(spec).replace(os.sep, "/"),
    ]
    base = spec.rsplit("/", 1)[-1]
    if "." not in base:
        for ext in _C_EXTENSIONS:
            candidates.append(
                os.path.normpath(os.path.join(os.path.dirname(src_path), spec + ext)).replace(
                    os.sep, "/"
                )
            )
            candidates.append(os.path.normpath(spec + ext).replace(os.sep, "/"))
    for cand in candidates:
        if cand in files and cand != src_path:
            return cand
    return None
