"""
File system scanning skills for repository analysis.

These functions are registered as AutoGen tool calls to provide
the LLM with real-time information about the target repository.
"""

from pathlib import Path

# The repo path is injected at runtime by the orchestrator
_REPO_PATH: str = "."


def set_repo_path(path: str) -> None:
    """Set the global repository path for all skill functions."""
    global _REPO_PATH
    _REPO_PATH = path


def _resolve(relative: str = "") -> Path:
    base = Path(_REPO_PATH).resolve()
    if relative:
        return base / relative
    return base


# ─── Skills ───────────────────────────────────────────────────────────────────


def scan_repository() -> dict:
    """
    Scan the repository and return its file/directory structure.

    Returns a summary of the top-level structure, total file count,
    and a sample of important files found.
    """
    repo = _resolve()
    if not repo.exists():
        return {"error": f"Repository path not found: {repo}"}

    total_files = 0
    top_level = []

    for entry in sorted(repo.iterdir()):
        if entry.name.startswith(".") and entry.name not in {
            ".github",
            ".gitlab",
            ".gitignore",
            ".cursorrules",
            ".env.example",
            ".devcontainer",
            ".vscode",
        }:
            continue
        if entry.is_dir():
            sub_count = sum(1 for _ in entry.rglob("*") if _.is_file())
            top_level.append({"name": entry.name, "type": "directory", "file_count": sub_count})
            total_files += sub_count
        else:
            top_level.append(
                {"name": entry.name, "type": "file", "size_bytes": entry.stat().st_size}
            )
            total_files += 1

    return {
        "repo_path": str(repo),
        "total_files": total_files,
        "top_level_entries": top_level[:30],  # Limit output
        "exists": True,
    }


def check_file_exists(filename: str) -> dict:
    """
    Check whether a specific file exists in the repository.

    Args:
        filename: File name or relative path to check (e.g. 'README.md', '.github/workflows/ci.yml')

    Returns:
        Dict with 'exists' bool, 'path', and optionally 'size_bytes'.
    """
    repo = _resolve()
    # Direct path check
    target = repo / filename
    if target.exists():
        stat = target.stat()
        return {
            "filename": filename,
            "exists": True,
            "path": str(target.relative_to(repo)),
            "size_bytes": stat.st_size,
            "is_empty": stat.st_size == 0,
        }

    # Recursive search for the filename (not path), skipping dependency dirs
    base_name = Path(filename).name
    _skip_dirs = {
        "node_modules",
        ".git",
        "__pycache__",
        "dist",
        "build",
        ".tox",
        "venv",
        ".venv",
        ".cache",
    }
    found = []
    for p in repo.rglob(base_name):
        parts = p.relative_to(repo).parts
        if any(part in _skip_dirs for part in parts):
            continue
        found.append(str(p.relative_to(repo)))

    if found:
        first = repo / found[0]
        return {
            "filename": filename,
            "exists": True,
            "path": found[0],
            "size_bytes": first.stat().st_size,
            "is_empty": first.stat().st_size == 0,
            "all_paths": found[:5],
        }

    return {"filename": filename, "exists": False}


def read_file_content(filename: str, max_lines: int = 100) -> dict:
    """
    Read the content of a file in the repository (up to max_lines).

    Args:
        filename: Relative path to the file
        max_lines: Maximum number of lines to return

    Returns:
        Dict with 'content' string and 'total_lines'.
    """
    repo = _resolve()
    target = repo / filename
    if not target.exists():
        # Try recursive search
        base_name = Path(filename).name
        for p in repo.rglob(base_name):
            target = p
            break

    if not target.exists() or not target.is_file():
        return {"filename": filename, "exists": False, "content": ""}

    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        content = "\n".join(lines[:max_lines])
        return {
            "filename": str(target.relative_to(repo)),
            "exists": True,
            "total_lines": total,
            "content": content,
            "truncated": total > max_lines,
        }
    except Exception as e:
        return {"filename": filename, "exists": True, "error": str(e)}


def list_files_by_extension(extension: str) -> dict:
    """
    List all files with a specific extension in the repository.

    Args:
        extension: File extension without dot (e.g. 'ts', 'py', 'yaml')

    Returns:
        Dict with list of relative file paths and count.
    """
    repo = _resolve()
    ext = extension.lstrip(".")
    pattern = f"*.{ext}"

    files = []
    for p in repo.rglob(pattern):
        # Skip node_modules, .git, __pycache__, dist, build
        parts = p.relative_to(repo).parts
        skip_dirs = {
            "node_modules",
            ".git",
            "__pycache__",
            "dist",
            "build",
            ".tox",
            "venv",
            ".venv",
        }
        if any(part in skip_dirs for part in parts):
            continue
        files.append(str(p.relative_to(repo)))

    return {
        "extension": ext,
        "count": len(files),
        "files": files[:50],  # Limit to 50 results
        "truncated": len(files) > 50,
    }


def analyze_directory_structure() -> dict:
    """
    Analyze the repository directory structure for depth, naming conventions,
    and organizational patterns.

    Returns:
        Dict with structure analysis including depth stats, naming patterns,
        and identification of common patterns like src/, tests/, docs/.
    """
    repo = _resolve()

    def get_dir_tree(path: Path, depth: int = 0, max_depth: int = 4) -> dict:
        if depth >= max_depth or not path.is_dir():
            return {}
        result = {}
        try:
            for entry in sorted(path.iterdir()):
                if entry.name.startswith(".") and entry.name not in {
                    ".github",
                    ".gitlab",
                    ".devcontainer",
                    ".vscode",
                }:
                    continue
                skip = {
                    "node_modules",
                    "__pycache__",
                    "dist",
                    "build",
                    ".tox",
                    "venv",
                    ".venv",
                    ".git",
                }
                if entry.name in skip:
                    continue
                if entry.is_dir():
                    result[entry.name + "/"] = get_dir_tree(entry, depth + 1, max_depth)
                else:
                    result[entry.name] = None
        except PermissionError:
            pass
        return result

    tree = get_dir_tree(repo)

    # Detect common patterns
    patterns = {
        "has_src_dir": (repo / "src").is_dir(),
        "has_tests_dir": any((repo / d).is_dir() for d in ["tests", "test", "__tests__", "spec"]),
        "has_docs_dir": any((repo / d).is_dir() for d in ["docs", "doc", "documentation"]),
        "has_github_dir": (repo / ".github").is_dir(),
        "has_devcontainer": (repo / ".devcontainer").is_dir(),
        "has_scripts_dir": any((repo / d).is_dir() for d in ["scripts", "bin", "tools"]),
    }

    # Measure average directory depth
    all_dirs = [p for p in repo.rglob("*") if p.is_dir()]
    skip_dirs = {"node_modules", "__pycache__", "dist", "build", ".git", ".tox", "venv", ".venv"}
    valid_dirs = [
        d for d in all_dirs if not any(part in skip_dirs for part in d.relative_to(repo).parts)
    ]
    depths = [len(d.relative_to(repo).parts) for d in valid_dirs]
    avg_depth = sum(depths) / len(depths) if depths else 0
    max_depth_found = max(depths) if depths else 0

    return {
        "tree": tree,
        "patterns": patterns,
        "avg_directory_depth": round(avg_depth, 2),
        "max_directory_depth": max_depth_found,
        "total_directories": len(valid_dirs),
        "semantic_naming": _check_semantic_naming(tree),
    }


def _check_semantic_naming(tree: dict) -> dict:
    """Check if top-level directory names are semantically meaningful."""
    semantic_names = {
        "src",
        "lib",
        "app",
        "api",
        "core",
        "modules",
        "services",
        "controllers",
        "models",
        "views",
        "utils",
        "helpers",
        "config",
        "tests",
        "test",
        "docs",
        "doc",
        "scripts",
        "bin",
        "tools",
        "migrations",
        "fixtures",
        "templates",
        "assets",
        "static",
        "components",
        "pages",
        "routes",
        "middleware",
        "plugins",
    }
    generic_names = {"misc", "stuff", "data", "temp", "tmp", "old", "new", "backup"}

    top_dirs = [k.rstrip("/") for k, v in tree.items() if isinstance(v, dict)]
    semantic_count = sum(1 for d in top_dirs if d.lower() in semantic_names)
    generic_count = sum(1 for d in top_dirs if d.lower() in generic_names)

    return {
        "top_level_dirs": top_dirs,
        "semantic_count": semantic_count,
        "generic_count": generic_count,
        "semantic_ratio": round(semantic_count / len(top_dirs), 2) if top_dirs else 0,
    }


def check_devcontainer() -> dict:
    """Check for devcontainer configuration for standardized dev environments."""
    repo = _resolve()
    devcontainer_paths = [
        ".devcontainer/devcontainer.json",
        ".devcontainer.json",
        ".devcontainer/Dockerfile",
    ]
    found = []
    for p in devcontainer_paths:
        full = repo / p
        if full.exists():
            found.append(p)

    # Also check for Nix
    has_nix = (
        (repo / "flake.nix").exists()
        or (repo / "shell.nix").exists()
        or (repo / "default.nix").exists()
    )
    # Check for Codespace
    has_codespace = (repo / ".devcontainer").is_dir()

    return {
        "has_devcontainer": bool(found),
        "devcontainer_files": found,
        "has_nix": has_nix,
        "has_codespace_config": has_codespace,
    }
