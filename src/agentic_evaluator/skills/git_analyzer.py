"""
Git repository and CI/CD analysis skills.

These functions analyze git history, CI configuration, test infrastructure,
version control practices, and security configurations.
"""

import re
import subprocess
from pathlib import Path

from .file_scanner import _resolve, list_files_by_extension


# ─── Git History Analysis ─────────────────────────────────────────────────────


def analyze_git_history() -> dict:
    """
    Analyze git commit history for conventions and practices.

    Checks for Conventional Commits usage, commit message quality,
    branch strategies, and PR/changelog configuration.
    """
    repo = _resolve()

    if not (repo / ".git").exists():
        return {"has_git": False, "message": "Not a git repository"}

    result = {
        "has_git": True,
        "conventional_commits": False,
        "commit_count": 0,
        "avg_message_length": 0,
        "has_pr_template": False,
        "has_changelog": False,
        "has_commitlint": False,
    }

    try:
        # Get recent commits
        proc = subprocess.run(
            ["git", "log", "--oneline", "-50"],
            capture_output=True, text=True, cwd=str(repo), timeout=10
        )
        if proc.returncode == 0:
            lines = [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]
            result["commit_count"] = len(lines)

            # Check for Conventional Commits pattern: type(scope): description
            cc_pattern = re.compile(r'^[0-9a-f]+ (feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)(\(.+\))?: .+')
            cc_matches = sum(1 for l in lines if cc_pattern.match(l))
            result["conventional_commits"] = cc_matches > len(lines) * 0.5 if lines else False
            result["conventional_commits_ratio"] = round(cc_matches / max(len(lines), 1), 2)

            # Average message length (excluding hash)
            msg_lengths = [len(l.split(" ", 1)[1]) if " " in l else 0 for l in lines]
            result["avg_message_length"] = round(sum(msg_lengths) / max(len(msg_lengths), 1), 1)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        result["git_error"] = "Could not run git log"

    # Check for PR template
    pr_template_paths = [
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/pull_request_template.md",
        "PULL_REQUEST_TEMPLATE.md",
    ]
    result["has_pr_template"] = any((repo / p).exists() for p in pr_template_paths)

    # Check for CHANGELOG
    result["has_changelog"] = any((repo / f).exists() for f in ["CHANGELOG.md", "CHANGELOG", "CHANGES.md"])

    # Check for commitlint
    commitlint_files = [".commitlintrc", ".commitlintrc.js", ".commitlintrc.json", "commitlint.config.js"]
    result["has_commitlint"] = any((repo / f).exists() for f in commitlint_files)

    # Check for release-please or semantic-release
    result["has_auto_release"] = (
        (repo / "release-please-config.json").exists() or
        (repo / ".releaserc").exists() or
        (repo / "release.config.js").exists()
    )

    return result


def check_ci_config() -> dict:
    """
    Check for CI/CD pipeline configuration.

    Looks for GitHub Actions, GitLab CI, CircleCI, Jenkins,
    and verifies whether CI runs tests and lint checks.
    """
    repo = _resolve()

    ci_systems = {
        "github_actions": (repo / ".github" / "workflows").is_dir(),
        "gitlab_ci": (repo / ".gitlab-ci.yml").exists(),
        "circleci": (repo / ".circleci").is_dir(),
        "jenkins": (repo / "Jenkinsfile").exists(),
        "travis": (repo / ".travis.yml").exists(),
        "drone": (repo / ".drone.yml").exists(),
    }

    has_ci = any(ci_systems.values())
    active_ci = [k for k, v in ci_systems.items() if v]

    # Analyze GitHub Actions workflows
    workflow_details = []
    if ci_systems["github_actions"]:
        workflow_dir = repo / ".github" / "workflows"
        for wf_file in workflow_dir.glob("*.yml"):
            try:
                content = wf_file.read_text(encoding="utf-8", errors="replace")
                workflow_details.append({
                    "name": wf_file.name,
                    "has_test": "test" in content.lower() or "pytest" in content or "jest" in content,
                    "has_lint": "lint" in content.lower() or "eslint" in content or "ruff" in content,
                    "has_build": "build" in content.lower(),
                    "triggers": _extract_triggers(content),
                })
            except Exception:
                pass

    runs_tests = any(w.get("has_test") for w in workflow_details)
    runs_lint = any(w.get("has_lint") for w in workflow_details)

    return {
        "has_ci": has_ci,
        "ci_systems": ci_systems,
        "active_ci": active_ci,
        "workflow_count": len(workflow_details),
        "workflow_details": workflow_details[:5],
        "runs_tests_in_ci": runs_tests,
        "runs_lint_in_ci": runs_lint,
        "has_complete_pipeline": has_ci and runs_tests,
    }


def _extract_triggers(content: str) -> list:
    """Extract workflow trigger events from GitHub Actions YAML."""
    triggers = []
    if "push:" in content:
        triggers.append("push")
    if "pull_request:" in content:
        triggers.append("pull_request")
    if "schedule:" in content:
        triggers.append("schedule")
    if "workflow_dispatch:" in content:
        triggers.append("manual")
    return triggers


def check_gitignore() -> dict:
    """
    Analyze .gitignore configuration for security and completeness.

    Checks if sensitive files, build artifacts, and environment files
    are properly excluded from version control.
    """
    repo = _resolve()

    gitignore_path = repo / ".gitignore"
    if not gitignore_path.exists():
        return {
            "has_gitignore": False,
            "missing_critical": ["no .gitignore file"],
        }

    content = gitignore_path.read_text(encoding="utf-8", errors="replace")
    patterns = content.splitlines()

    critical_patterns = {
        ".env": any(".env" in p for p in patterns),
        "node_modules": any("node_modules" in p for p in patterns),
        "__pycache__": any("__pycache__" in p for p in patterns),
        "dist": any(p.strip() in {"/dist", "dist/", "dist"} for p in patterns),
        "build": any(p.strip() in {"/build", "build/", "build"} for p in patterns),
        "*.key": any("*.key" in p or "*.pem" in p or "*.p12" in p for p in patterns),
        ".DS_Store": any(".DS_Store" in p for p in patterns),
    }

    missing = [k for k, v in critical_patterns.items() if not v]

    # Check if .env file exists (would be a security issue)
    env_in_repo = (repo / ".env").exists()

    # Check for secret scanning config
    has_secret_scan = (
        (repo / ".gitleaks.toml").exists() or
        (repo / ".git-secrets").exists() or
        (repo / ".truffleHog.json").exists()
    )

    return {
        "has_gitignore": True,
        "pattern_count": len([p for p in patterns if p.strip() and not p.startswith("#")]),
        "critical_patterns": critical_patterns,
        "missing_critical": missing,
        "env_file_committed": env_in_repo,
        "has_secret_scanning": has_secret_scan,
        "security_score": (
            "good" if not missing and not env_in_repo else
            "ok" if len(missing) <= 2 and not env_in_repo else
            "poor"
        ),
    }


def check_adr_records() -> dict:
    """
    Check for Architecture Decision Records (ADR) in the repository.

    Looks for ADR directories, counts records, and checks for
    standard ADR format compliance.
    """
    repo = _resolve()

    adr_dirs = ["docs/adr", "docs/decisions", "adr", "docs/architecture", "architecture/decisions"]
    found_dir = None
    for d in adr_dirs:
        if (repo / d).is_dir():
            found_dir = d
            break

    if not found_dir:
        # Also check for individual ADR files in docs
        adr_files = list(repo.rglob("ADR-*.md")) + list(repo.rglob("adr-*.md")) + list(repo.rglob("*-adr.md"))
        if adr_files:
            return {
                "has_adr": True,
                "adr_count": len(adr_files),
                "adr_dir": "scattered",
                "has_adr_dir": False,
                "sample_files": [str(f.relative_to(repo)) for f in adr_files[:5]],
            }
        return {"has_adr": False, "adr_count": 0}

    adr_path = repo / found_dir
    adr_files = list(adr_path.glob("*.md"))

    # Check for CONTRIBUTING.md and CLAUDE.md (knowledge base)
    has_contributing = (repo / "CONTRIBUTING.md").exists()
    has_claude_md = (repo / "CLAUDE.md").exists()
    has_cursorrules = (repo / ".cursorrules").exists() or (repo / ".cursor" / "rules").is_dir()

    return {
        "has_adr": True,
        "adr_count": len(adr_files),
        "adr_dir": found_dir,
        "has_adr_dir": True,
        "sample_files": [f.name for f in adr_files[:5]],
        "has_contributing": has_contributing,
        "has_claude_md": has_claude_md,
        "has_cursorrules": has_cursorrules,
    }


def count_test_files() -> dict:
    """
    Count and categorize test files in the repository.

    Distinguishes unit tests, integration tests, and E2E tests.
    Also checks for test configuration files and coverage reports.
    """
    repo = _resolve()

    # Find test files by various naming conventions
    test_patterns = [
        # JS/TS
        "*.test.ts", "*.test.tsx", "*.test.js",
        "*.spec.ts", "*.spec.tsx", "*.spec.js",
        # Python
        "test_*.py", "*_test.py",
        # Go
        "*_test.go",
        # Java/Groovy
        "*Test.java", "*Tests.java", "*IT.java", "*Spec.groovy",
    ]

    all_test_files = []
    for pattern in test_patterns:
        for p in repo.rglob(pattern):
            parts = p.relative_to(repo).parts
            skip_dirs = {"node_modules", ".git", "__pycache__", "dist", "build"}
            if not any(part in skip_dirs for part in parts):
                all_test_files.append(str(p.relative_to(repo)))

    # Categorize tests
    e2e_files = [f for f in all_test_files if any(kw in f.lower() for kw in ["e2e", "playwright", "cypress", "selenium"])]
    integration_files = [f for f in all_test_files if any(kw in f.lower() for kw in ["integration", "integ", "int"])]
    unit_files = [f for f in all_test_files if f not in e2e_files and f not in integration_files]

    # Test configuration files
    test_configs = {
        # JS/TS
        "jest": any((repo / f).exists() for f in ["jest.config.js", "jest.config.ts", "jest.config.json"]),
        "vitest": (repo / "vitest.config.ts").exists() or (repo / "vitest.config.js").exists(),
        "mocha": any((repo / f).exists() for f in [".mocharc.js", ".mocharc.yml"]),
        "playwright": (repo / "playwright.config.ts").exists(),
        "cypress": (repo / "cypress.config.ts").exists() or (repo / "cypress.json").exists(),
        # Python
        "pytest": (repo / "pytest.ini").exists() or (repo / "pyproject.toml").exists(),
        # Go (uses built-in `go test`)
        "go_test": (repo / "go.mod").exists(),
        # Java
        "junit": any(repo.rglob("*Test.java")) or any(repo.rglob("*Tests.java")),
        "testng": any(repo.rglob("testng.xml")),
    }

    # Coverage config
    has_coverage = (
        (repo / ".nycrc").exists() or
        (repo / "coverage.json").exists() or
        any("coverage" in str(p) for p in repo.rglob("*.json") if "config" in str(p))
    )

    # Test directory structure
    test_dirs = [d for d in ["tests", "test", "__tests__", "spec"] if (repo / d).is_dir()]

    return {
        "total_test_files": len(all_test_files),
        "unit_tests": len(unit_files),
        "integration_tests": len(integration_files),
        "e2e_tests": len(e2e_files),
        "test_configs": test_configs,
        "active_test_frameworks": [k for k, v in test_configs.items() if v],
        "has_coverage_config": has_coverage,
        "test_directories": test_dirs,
        "has_tests": len(all_test_files) > 0,
    }


def check_dependency_transparency() -> dict:
    """
    Check dependency management and transparency.

    Looks for lock files, circular dependency detection,
    and dependency audit configurations.
    """
    repo = _resolve()

    lock_files = {
        "package-lock.json": (repo / "package-lock.json").exists(),
        "yarn.lock": (repo / "yarn.lock").exists(),
        "pnpm-lock.yaml": (repo / "pnpm-lock.yaml").exists(),
        "poetry.lock": (repo / "poetry.lock").exists(),
        "Pipfile.lock": (repo / "Pipfile.lock").exists(),
        "uv.lock": (repo / "uv.lock").exists(),
        "cargo.lock": (repo / "Cargo.lock").exists(),
        "go.sum": (repo / "go.sum").exists(),
    }

    has_any_lock = any(lock_files.values())
    active_locks = [k for k, v in lock_files.items() if v]

    # Check for circular dependency tools
    pkg_json = repo / "package.json"
    has_madge = has_deptrac = False
    if pkg_json.exists():
        content = pkg_json.read_text(encoding="utf-8", errors="replace")
        has_madge = "madge" in content
        has_deptrac = "deptrac" in content

    # Check for dependency security audit configs
    has_audit = any([
        (repo / ".snyk").exists(),
        (repo / "dependabot.yml").exists(),
        (repo / ".github" / "dependabot.yml").exists(),
        (repo / ".github" / "renovate.json").exists(),
        (repo / "renovate.json").exists(),
    ])

    # Count total dependencies
    total_deps = 0
    if pkg_json.exists():
        try:
            import json
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            total_deps = len(data.get("dependencies", {})) + len(data.get("devDependencies", {}))
        except Exception:
            pass

    return {
        "lock_files": lock_files,
        "has_any_lock_file": has_any_lock,
        "active_lock_files": active_locks,
        "has_circular_dep_detection": has_madge or has_deptrac,
        "has_dependency_audit": has_audit,
        "total_dependencies": total_deps,
        "dependency_tools": {
            "madge": has_madge,
            "deptrac": has_deptrac,
        },
        "audit_tools": {
            "snyk": (repo / ".snyk").exists(),
            "dependabot": (repo / ".github" / "dependabot.yml").exists(),
            "renovate": (repo / "renovate.json").exists(),
        },
    }
