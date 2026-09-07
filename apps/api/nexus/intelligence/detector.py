"""Language detection for V1 (Python + JS/TS + C/C++). Go/Java stubbed for later."""

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
}

SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        "dist",
        "build",
        ".next",
        "coverage",
        ".pytest_cache",
    }
)

# Future languages (V2): map extension here and add a parser module.
PLANNED_EXTENSIONS: dict[str, str] = {".go": "go", ".java": "java"}


def detect_language(path: str) -> str | None:
    lowered = path.lower()
    for ext, lang in SUPPORTED_EXTENSIONS.items():
        if lowered.endswith(ext):
            return lang
    return None


def is_planned(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in PLANNED_EXTENSIONS)
