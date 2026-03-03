"""
Code quality analysis skills for repository evaluation.

These functions analyze code structure, type system usage, naming conventions,
documentation quality, and architectural patterns.
"""

import re
from pathlib import Path

from .file_scanner import _resolve, list_files_by_extension

# ─── Type System Analysis ─────────────────────────────────────────────────────


def check_type_annotations() -> dict:
    """
    Analyze type system usage in the repository.

    Checks for TypeScript, Python, Go, Java, Vue type usage and
    reports the primary language with type system quality.
    """
    repo = _resolve()

    ts_files = list_files_by_extension("ts")
    tsx_files = list_files_by_extension("tsx")
    js_files = list_files_by_extension("js")
    py_files = list_files_by_extension("py")
    go_files = list_files_by_extension("go")
    java_files = list_files_by_extension("java")
    vue_files = list_files_by_extension("vue")

    result = {
        "typescript_files": ts_files["count"],
        "tsx_files": tsx_files["count"],
        "javascript_files": js_files["count"],
        "python_files": py_files["count"],
        "go_files": go_files["count"],
        "java_files": java_files["count"],
        "vue_files": vue_files["count"],
        "language": "unknown",
        "type_system": "none",
        "strict_mode": False,
        "any_count": 0,
        "pydantic_usage": False,
        "tsconfig_exists": False,
    }

    # 判断主语言（按文件数量）
    lang_counts = {
        "TypeScript": ts_files["count"] + tsx_files["count"] + vue_files["count"],
        "Python": py_files["count"],
        "Go": go_files["count"],
        "Java": java_files["count"],
        "JavaScript": js_files["count"],
    }
    primary = max(lang_counts, key=lang_counts.get)
    result["language"] = primary if lang_counts[primary] > 0 else "unknown"

    if primary == "TypeScript":
        result["type_system"] = "static"
        tsconfig = repo / "tsconfig.json"
        if tsconfig.exists():
            result["tsconfig_exists"] = True
            content = tsconfig.read_text(encoding="utf-8", errors="replace")
            result["strict_mode"] = '"strict": true' in content or '"strict":true' in content
        any_count = 0
        for f in ts_files["files"] + tsx_files["files"]:
            try:
                content = (repo / f).read_text(encoding="utf-8", errors="replace")
                any_count += len(re.findall(r"\bany\b", content))
            except Exception:
                pass
        result["any_count"] = any_count

    elif primary == "Python":
        result["language"] = "Python"
        typed_files = 0
        pydantic = False
        for f in py_files["files"][:20]:
            try:
                content = (repo / f).read_text(encoding="utf-8", errors="replace")
                if "from typing import" in content or ": " in content or "-> " in content:
                    typed_files += 1
                if "pydantic" in content.lower() or "BaseModel" in content:
                    pydantic = True
            except Exception:
                pass
        result["pydantic_usage"] = pydantic
        result["typed_file_ratio"] = round(typed_files / max(py_files["count"], 1), 2)
        result["type_system"] = (
            "pydantic"
            if pydantic
            else ("partial" if typed_files / max(py_files["count"], 1) > 0.5 else "none")
        )

    elif primary == "Go":
        result["type_system"] = "static"  # Go is statically typed
        result["strict_mode"] = True  # Go enforces types at compile time
        # Count interface definitions as a measure of type system richness
        interface_count = 0
        source_files = [f for f in go_files["files"] if not f.endswith("_test.go")]
        for f in source_files[:20]:
            try:
                content = (repo / f).read_text(encoding="utf-8", errors="replace")
                interface_count += len(re.findall(r"\btype\s+\w+\s+interface\s*\{", content))
            except Exception:
                pass
        result["go_interface_count"] = interface_count
        result["has_generics"] = any(
            "[T " in (repo / f).read_text(encoding="utf-8", errors="replace")
            for f in source_files[:10]
            if (repo / f).exists()
        )

    elif primary == "Java":
        result["type_system"] = "static"
        result["strict_mode"] = True
        # Check for generics / annotations usage
        generic_count = 0
        annotation_count = 0
        for f in java_files["files"][:20]:
            try:
                content = (repo / f).read_text(encoding="utf-8", errors="replace")
                generic_count += len(re.findall(r"<[A-Z]\w*(?:,\s*[A-Z]\w*)*>", content))
                annotation_count += len(re.findall(r"@\w+", content))
            except Exception:
                pass
        result["java_generics_usage"] = generic_count
        result["java_annotation_count"] = annotation_count

    # Check for type definition files (cross-language)
    result["has_type_definitions"] = any(
        [
            (repo / "types").is_dir(),
            (repo / "src" / "types").is_dir(),
            any(repo.rglob("*.d.ts")),
        ]
    )

    return result


def check_naming_consistency() -> dict:
    """
    Analyze naming convention consistency across the repository.

    Checks file naming patterns for TypeScript, Python, Go, Java, and Vue,
    detects mixed conventions, and looks for linter naming rules.
    """
    repo = _resolve()

    ts_files = list_files_by_extension("ts")["files"]
    py_files = list_files_by_extension("py")["files"]
    go_files = [f for f in list_files_by_extension("go")["files"] if not f.endswith("_test.go")]
    java_files = list_files_by_extension("java")["files"]
    vue_files = list_files_by_extension("vue")["files"]
    all_code_files = ts_files + py_files + go_files + java_files + vue_files

    # Analyze file naming patterns
    kebab = camel = pascal = snake = other = 0
    for f in all_code_files:
        name = Path(f).stem
        if re.match(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", name):
            kebab += 1
        elif re.match(r"^[a-z][a-zA-Z0-9]*$", name) and any(c.isupper() for c in name):
            camel += 1
        elif re.match(r"^[A-Z][a-zA-Z0-9]*$", name):
            pascal += 1
        elif re.match(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", name):
            snake += 1
        else:
            other += 1

    total = max(len(all_code_files), 1)
    dominant_style = max(
        [
            ("kebab-case", kebab),
            ("camelCase", camel),
            ("PascalCase", pascal),
            ("snake_case", snake),
        ],
        key=lambda x: x[1],
    )[0]
    dominant_pct = max(kebab, camel, pascal, snake) / total

    # Check ESLint config for naming rules
    eslint_configs = [
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.json",
        ".eslintrc.yaml",
        "eslint.config.js",
        "eslint.config.mjs",
    ]
    has_eslint = any((repo / f).exists() for f in eslint_configs)
    has_naming_rule = False
    if has_eslint:
        for cfg in eslint_configs:
            p = repo / cfg
            if p.exists():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    if "naming-convention" in content or "camelcase" in content:
                        has_naming_rule = True
                except Exception:
                    pass

    return {
        "file_naming": {
            "kebab_case": kebab,
            "camelCase": camel,
            "PascalCase": pascal,
            "snake_case": snake,
            "other": other,
        },
        "dominant_style": dominant_style,
        "consistency_ratio": round(dominant_pct, 2),
        "is_consistent": dominant_pct > 0.7,
        "has_eslint": has_eslint,
        "has_naming_rule": has_naming_rule,
    }


def check_inline_documentation() -> dict:
    """
    Analyze quality of inline documentation and code comments.

    Checks for JSDoc/docstring/GoDoc/Javadoc coverage on public APIs,
    comment density across TypeScript, Python, Go, Java, and Vue files.
    """
    repo = _resolve()

    ts_files = list_files_by_extension("ts")["files"]
    py_files = list_files_by_extension("py")["files"]
    go_files = [f for f in list_files_by_extension("go")["files"] if not f.endswith("_test.go")]
    java_files = list_files_by_extension("java")["files"]
    vue_files = list_files_by_extension("vue")["files"]

    jsdoc_files = 0
    docstring_files = 0
    godoc_files = 0  # Go exported symbol with preceding // comment
    javadoc_files = 0  # Java /** ... */ style
    total_comment_lines = 0
    total_code_lines = 0
    has_todo_links = False

    sample = (ts_files + py_files + go_files + java_files + vue_files)[:40]
    for f in sample:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            total_code_lines += len(lines)
            comment_lines = sum(
                1
                for line in lines
                if line.strip().startswith("//")
                or line.strip().startswith("#")
                or line.strip().startswith("*")
                or line.strip().startswith("/*")
                or line.strip().startswith('"""')
                or line.strip().startswith("'''")
            )
            total_comment_lines += comment_lines

            if "/**" in content or "@param" in content or "@returns" in content:
                jsdoc_files += 1
            if '"""' in content or "'''" in content:
                docstring_files += 1
            # GoDoc: exported identifier preceded by // comment
            if re.search(r"// [A-Z]\w+", content) and f.endswith(".go"):
                godoc_files += 1
            # Javadoc
            if "/**" in content and f.endswith(".java"):
                javadoc_files += 1
            if re.search(r"TODO\s*\(#\d+\)", content) or re.search(r"TODO\s*\[#\d+\]", content):
                has_todo_links = True

        except Exception:
            pass

    comment_ratio = total_comment_lines / max(total_code_lines, 1)

    # Check for module-level README files in subdirectories
    subdir_readmes = sum(1 for p in repo.rglob("README.md") if p.parent != repo)

    return {
        "jsdoc_files": jsdoc_files,
        "docstring_files": docstring_files,
        "godoc_files": godoc_files,
        "javadoc_files": javadoc_files,
        "comment_ratio": round(comment_ratio, 3),
        "has_todo_issue_links": has_todo_links,
        "subdir_readmes": subdir_readmes,
        "coverage_quality": (
            "high" if comment_ratio > 0.15 else "medium" if comment_ratio > 0.05 else "low"
        ),
    }


# ─── Schema & Validation Analysis ────────────────────────────────────────────


def check_schema_validation() -> dict:
    """
    Check for data validation and schema definition mechanisms.

    Looks for Zod, Joi, Pydantic, JSON Schema, class-validator usage
    and whether schemas are the Single Source of Truth for types.
    """
    repo = _resolve()

    schema_tools = {
        "zod": False,
        "joi": False,
        "yup": False,
        "class_validator": False,
        "pydantic": False,
        "json_schema": False,
        "prisma": False,
        "typeorm": False,
        "sqlalchemy": False,
    }

    # Check package.json for JS validators
    pkg_json = repo / "package.json"
    if pkg_json.exists():
        content = pkg_json.read_text(encoding="utf-8", errors="replace")
        if "zod" in content:
            schema_tools["zod"] = True
        if '"joi"' in content or "'joi'" in content:
            schema_tools["joi"] = True
        if "yup" in content:
            schema_tools["yup"] = True
        if "class-validator" in content:
            schema_tools["class_validator"] = True
        if "prisma" in content:
            schema_tools["prisma"] = True
        if "typeorm" in content:
            schema_tools["typeorm"] = True

    # Check Python requirements
    for req_file in ["requirements.txt", "pyproject.toml", "Pipfile"]:
        p = repo / req_file
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace")
            if "pydantic" in content.lower():
                schema_tools["pydantic"] = True
            if "sqlalchemy" in content.lower():
                schema_tools["sqlalchemy"] = True

    # Check for z.infer pattern (Zod SSoT)
    has_zinfer = False
    has_pydantic_ssot = False
    ts_files = list_files_by_extension("ts")["files"]
    for f in ts_files[:20]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            if "z.infer" in content:
                has_zinfer = True
        except Exception:
            pass

    # Check for Prisma schema
    has_prisma_schema = any(repo.rglob("schema.prisma"))

    # Count schema files
    schema_files = (
        list(repo.rglob("*.schema.ts"))
        + list(repo.rglob("*.schema.json"))
        + list(repo.rglob("*schema*.py"))
    )

    any_validation = any(schema_tools.values())

    return {
        "schema_tools": schema_tools,
        "has_any_validation": any_validation,
        "has_schema_ssot": has_zinfer or has_pydantic_ssot,
        "has_prisma_schema": has_prisma_schema,
        "schema_file_count": len(schema_files),
        "active_tools": [k for k, v in schema_tools.items() if v],
    }


def check_module_interfaces() -> dict:
    """
    Check for module interface definitions and dependency inversion patterns.

    Looks for TypeScript interfaces, abstract classes, barrel exports,
    DI container usage, and module boundary patterns.
    """
    repo = _resolve()

    ts_files = list_files_by_extension("ts")["files"]

    interface_count = 0
    abstract_count = 0
    barrel_exports = 0
    di_usage = False

    for f in ts_files[:30]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            interface_count += len(re.findall(r"\binterface\s+\w+", content))
            abstract_count += len(re.findall(r"\babstract\s+class\s+", content))
            if (
                "inversify" in content
                or "tsyringe" in content
                or "@Injectable" in content
                or "@inject" in content
            ):
                di_usage = True
        except Exception:
            pass

    # Count barrel exports (index.ts files)
    index_files = [f for f in ts_files if Path(f).name == "index.ts"]
    barrel_exports = len(index_files)

    # Python: check for abstract base classes
    py_files = list_files_by_extension("py")["files"]
    py_abstract = 0
    for f in py_files[:20]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            py_abstract += len(re.findall(r"\bABC\b|\babstractmethod\b|\bProtocol\b", content))
        except Exception:
            pass

    return {
        "typescript_interfaces": interface_count,
        "abstract_classes": abstract_count + py_abstract,
        "barrel_exports": barrel_exports,
        "di_container_usage": di_usage,
        "has_interface_layer": interface_count > 5 or abstract_count > 2,
    }


def check_env_config() -> dict:
    """
    Check environment configuration management.

    Looks for .env.example, config schema validation, multi-environment
    support, and separation of sensitive vs non-sensitive config.
    """
    repo = _resolve()

    env_files = {
        ".env.example": (repo / ".env.example").exists(),
        ".env.template": (repo / ".env.template").exists(),
        ".env.sample": (repo / ".env.sample").exists(),
        ".env": (repo / ".env").exists(),  # Should NOT be committed
    }

    # Check .env.example content quality
    env_example_quality = {}
    for f in [".env.example", ".env.template", ".env.sample"]:
        p = repo / f
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace")
            lines = [
                line for line in content.splitlines() if line.strip() and not line.startswith("#")
            ]
            comment_lines = [line for line in content.splitlines() if line.startswith("#")]
            env_example_quality = {
                "file": f,
                "var_count": len(lines),
                "comment_lines": len(comment_lines),
                "has_comments": len(comment_lines) > 0,
            }
            break

    # Check for config validation libraries
    pkg_json = repo / "package.json"
    has_envalid = has_dotenv_safe = False
    if pkg_json.exists():
        content = pkg_json.read_text(encoding="utf-8", errors="replace")
        has_envalid = "envalid" in content
        has_dotenv_safe = "dotenv-safe" in content

    # Check for multi-environment configs
    env_profiles = [
        (repo / ".env.development").exists(),
        (repo / ".env.production").exists(),
        (repo / ".env.test").exists(),
        (repo / "config" / "development.json").exists(),
        (repo / "config" / "production.json").exists(),
    ]

    return {
        "env_files": env_files,
        "has_env_example": any(
            [env_files[".env.example"], env_files[".env.template"], env_files[".env.sample"]]
        ),
        "env_committed": env_files[".env"],
        "env_example_quality": env_example_quality,
        "has_schema_validation": has_envalid or has_dotenv_safe,
        "has_multi_env": any(env_profiles),
        "validation_tools": {
            "envalid": has_envalid,
            "dotenv_safe": has_dotenv_safe,
        },
    }


def check_lint_config() -> dict:
    """
    Check linting and formatting tool configuration.

    Looks for ESLint, Prettier, Ruff, Black, pre-commit hooks,
    EditorConfig, and whether lint is enforced in CI.
    """
    repo = _resolve()

    configs = {
        # JS/TS
        "eslint": any(
            (repo / f).exists()
            for f in [
                ".eslintrc",
                ".eslintrc.js",
                ".eslintrc.json",
                ".eslintrc.yaml",
                "eslint.config.js",
                "eslint.config.mjs",
            ]
        ),
        "prettier": any(
            (repo / f).exists()
            for f in [".prettierrc", ".prettierrc.js", ".prettierrc.json", "prettier.config.js"]
        ),
        # Python
        "ruff": (repo / "ruff.toml").exists() or _check_pyproject_tool(repo, "ruff"),
        "black": (repo / ".black").exists() or _check_pyproject_tool(repo, "black"),
        # Go
        "golangci_lint": any(
            (repo / f).exists()
            for f in [".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json"]
        ),
        # Java
        "checkstyle": any(repo.rglob("checkstyle*.xml")),
        "pmd": any(repo.rglob("pmd*.xml")),
        "spotbugs": any(repo.rglob("spotbugs*.xml")),
        # Universal
        "editorconfig": (repo / ".editorconfig").exists(),
    }

    # Check pre-commit hooks
    has_husky = (repo / ".husky").is_dir()
    has_pre_commit = (repo / ".pre-commit-config.yaml").exists()
    has_lint_staged = False
    pkg_json = repo / "package.json"
    if pkg_json.exists():
        content = pkg_json.read_text(encoding="utf-8", errors="replace")
        has_lint_staged = "lint-staged" in content

    return {
        "configs": configs,
        "has_any_linter": any(configs.values()),
        "has_husky": has_husky,
        "has_pre_commit": has_pre_commit,
        "has_lint_staged": has_lint_staged,
        "has_pre_commit_hooks": has_husky or has_pre_commit,
        "active_tools": [k for k, v in configs.items() if v],
    }


def _check_pyproject_tool(repo: Path, tool: str) -> bool:
    p = repo / "pyproject.toml"
    if p.exists():
        return f"[tool.{tool}]" in p.read_text(encoding="utf-8", errors="replace")
    return False


def check_build_scripts() -> dict:
    """
    Check for build automation scripts and entry points.

    Looks for Makefile, Taskfile, docker-compose, npm scripts, and
    evaluates coverage of common development operations.
    """
    repo = _resolve()

    has_makefile = (repo / "Makefile").exists()
    has_taskfile = any((repo / f).exists() for f in ["Taskfile.yml", "Taskfile.yaml", "tasks.py"])
    has_justfile = (repo / "justfile").exists() or (repo / "Justfile").exists()
    has_docker_compose = any(
        (repo / f).exists()
        for f in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]
    )

    # Check npm scripts
    npm_scripts = {}
    pkg_json = repo / "package.json"
    if pkg_json.exists():
        try:
            import json

            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            npm_scripts = data.get("scripts", {})
        except Exception:
            pass

    # Check Makefile targets
    make_targets = []
    if has_makefile:
        try:
            content = (repo / "Makefile").read_text(encoding="utf-8", errors="replace")
            make_targets = re.findall(r"^(\w[\w-]*)\s*:", content, re.MULTILINE)
        except Exception:
            pass

    important_ops = ["dev", "build", "test", "lint", "clean", "deploy"]
    all_scripts = set(npm_scripts.keys()) | set(make_targets)
    covered_ops = [op for op in important_ops if any(op in s for s in all_scripts)]

    return {
        "has_makefile": has_makefile,
        "has_taskfile": has_taskfile,
        "has_justfile": has_justfile,
        "has_docker_compose": has_docker_compose,
        "npm_scripts": list(npm_scripts.keys()),
        "make_targets": make_targets[:20],
        "covered_operations": covered_ops,
        "operation_coverage": round(len(covered_ops) / len(important_ops), 2),
        "has_help_target": "help" in make_targets or "help" in npm_scripts,
    }


def check_error_handling() -> dict:
    """
    Analyze error handling patterns in the codebase.

    Looks for custom error types, structured error responses,
    catch-all patterns, and error documentation.
    """
    repo = _resolve()

    ts_files = list_files_by_extension("ts")["files"]
    py_files = list_files_by_extension("py")["files"]
    go_files = [f for f in list_files_by_extension("go")["files"] if not f.endswith("_test.go")]
    java_files = list_files_by_extension("java")["files"]

    custom_error_classes = 0
    catch_all_count = 0
    structured_errors = 0
    error_enum_found = False
    go_error_wrapping = 0  # fmt.Errorf %w / errors.Is / errors.As
    java_custom_exceptions = 0

    for f in (ts_files + py_files)[:20]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            custom_error_classes += len(
                re.findall(
                    r"class\s+\w*Error\w*\s*extends\s+Error|class\s+\w*Exception\w*\s*\(Exception\)",
                    content,
                )
            )
            catch_all_count += len(
                re.findall(r"catch\s*\(\w+\)\s*\{\s*\}|except\s+Exception\s+as", content)
            )
            if "statusCode" in content or "error_code" in content or "ErrorCode" in content:
                structured_errors += 1
            if re.search(r"enum\s+\w*Error\w*\s*{|ErrorCode\s*=", content):
                error_enum_found = True
        except Exception:
            pass

    # Go error patterns
    for f in go_files[:20]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            go_error_wrapping += len(
                re.findall(r"fmt\.Errorf\([^)]*%w|errors\.Is\(|errors\.As\(", content)
            )
            # Custom error types: type XxxError struct
            custom_error_classes += len(re.findall(r"type\s+\w*[Ee]rror\w*\s+struct", content))
            if re.search(r"type\s+\w*[Ee]rror[Cc]ode\b|ErrCode\s+\w+\s+=", content):
                error_enum_found = True
        except Exception:
            pass

    # Java exception patterns
    for f in java_files[:20]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            java_custom_exceptions += len(
                re.findall(r"class\s+\w+Exception\s+extends|class\s+\w+Error\s+extends", content)
            )
            if re.search(r"@ResponseStatus|ResponseEntity|ErrorCode", content):
                structured_errors += 1
        except Exception:
            pass

    custom_error_classes += java_custom_exceptions

    return {
        "custom_error_classes": custom_error_classes,
        "catch_all_count": catch_all_count,
        "structured_error_count": structured_errors,
        "has_error_enum": error_enum_found,
        "has_custom_errors": custom_error_classes > 0,
        "go_error_wrapping_count": go_error_wrapping,
        "java_custom_exceptions": java_custom_exceptions,
        "quality": (
            "high"
            if custom_error_classes > 5 and error_enum_found
            else "medium"
            if custom_error_classes > 0 or go_error_wrapping > 3
            else "low"
        ),
    }


def check_logging_config() -> dict:
    """Check for structured logging configuration and observability setup."""
    repo = _resolve()

    # Check for logging libraries
    logging_tools = {
        "winston": False,
        "pino": False,
        "bunyan": False,
        "structlog": False,
        "loguru": False,
        "opentelemetry": False,
    }

    pkg_json = repo / "package.json"
    if pkg_json.exists():
        content = pkg_json.read_text(encoding="utf-8", errors="replace")
        for tool in ["winston", "pino", "bunyan"]:
            if f'"{tool}"' in content:
                logging_tools[tool] = True
        if "opentelemetry" in content:
            logging_tools["opentelemetry"] = True

    for req_file in ["requirements.txt", "pyproject.toml"]:
        p = repo / req_file
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace")
            if "structlog" in content:
                logging_tools["structlog"] = True
            if "loguru" in content:
                logging_tools["loguru"] = True
            if "opentelemetry" in content:
                logging_tools["opentelemetry"] = True

    # Check for vscode debug config
    has_launch_json = (repo / ".vscode" / "launch.json").exists()
    has_health_endpoint = False
    ts_files = list_files_by_extension("ts")["files"]
    for f in ts_files[:15]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            if "/health" in content or "healthcheck" in content.lower():
                has_health_endpoint = True
                break
        except Exception:
            pass

    return {
        "logging_tools": logging_tools,
        "has_any_logging": any(logging_tools.values()),
        "has_vscode_debug": has_launch_json,
        "has_health_endpoint": has_health_endpoint,
        "has_tracing": logging_tools["opentelemetry"],
        "active_tools": [k for k, v in logging_tools.items() if v],
    }


# ─── Architecture & Design Pattern Analysis ───────────────────────────────────


def check_design_patterns() -> dict:
    """
    Analyze consistency of design patterns used in the codebase.

    Looks for ADR records, layer separation (Controller-Service-Repository),
    consistent API patterns, and error handling patterns.
    """
    repo = _resolve()

    # Check ADR directory
    adr_dirs = ["docs/adr", "docs/decisions", "adr", "architecture/decisions"]
    has_adr = any((repo / d).is_dir() for d in adr_dirs)

    # Check for consistent layered architecture
    layered_patterns = {
        "controllers": any(repo.rglob("*controller*")) or any(repo.rglob("*Controller*")),
        "services": any(repo.rglob("*service*")) or any(repo.rglob("*Service*")),
        "repositories": any(repo.rglob("*repository*")) or any(repo.rglob("*Repository*")),
        "models": any(repo.rglob("*model*")) or any(repo.rglob("*Model*")),
    }

    layer_count = sum(1 for v in layered_patterns.values() if v)

    # Check for code generation templates
    has_plop = (repo / "plopfile.js").exists() or (repo / "plopfile.ts").exists()
    has_hygen = (repo / "_templates").is_dir()

    return {
        "has_adr": has_adr,
        "layered_patterns": layered_patterns,
        "layer_count": layer_count,
        "has_consistent_layers": layer_count >= 3,
        "has_code_generators": has_plop or has_hygen,
        "generation_tools": {
            "plop": has_plop,
            "hygen": has_hygen,
        },
    }


def check_extensibility() -> dict:
    """
    Check for extensibility mechanisms in the codebase.

    Looks for plugin systems, middleware chains, hook patterns,
    and strategy/factory patterns.
    """
    repo = _resolve()

    ts_files = list_files_by_extension("ts")["files"]
    py_files = list_files_by_extension("py")["files"]

    plugin_dir = (repo / "plugins").is_dir() or (repo / "src" / "plugins").is_dir()
    middleware_dir = (repo / "middleware").is_dir() or any(repo.rglob("*middleware*"))

    factory_pattern = 0
    strategy_pattern = 0
    hook_pattern = 0

    for f in (ts_files + py_files)[:25]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            if re.search(r"Factory\s*[({<]|factory\s*\(", content):
                factory_pattern += 1
            if re.search(r"Strategy\b|IStrategy\b|strategy\s*=", content):
                strategy_pattern += 1
            if re.search(r"use\w+Hook|addHook|registerHook|@Hook", content):
                hook_pattern += 1
        except Exception:
            pass

    # Count excessive switch/if-else (anti-pattern for extensibility)
    large_switch_count = 0
    for f in (ts_files + py_files)[:20]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            matches = re.findall(r"\bswitch\s*\(", content)
            if len(matches) > 3:
                large_switch_count += 1
        except Exception:
            pass

    return {
        "has_plugin_dir": plugin_dir,
        "has_middleware": middleware_dir,
        "factory_pattern_count": factory_pattern,
        "strategy_pattern_count": strategy_pattern,
        "hook_pattern_count": hook_pattern,
        "large_switch_files": large_switch_count,
        "extensibility_score": (
            "high"
            if plugin_dir or (factory_pattern + strategy_pattern + hook_pattern) > 5
            else "medium"
            if middleware_dir or (factory_pattern + strategy_pattern) > 2
            else "low"
        ),
    }


def check_refactoring_safety() -> dict:
    """
    Evaluate the safety net available for refactoring.

    Combines type system, test coverage, and CI information
    to assess refactoring risk.
    """
    repo = _resolve()

    # Check for type system
    has_typescript = list_files_by_extension("ts")["count"] > 0
    has_python_types = False
    py_files = list_files_by_extension("py")["files"]
    for f in py_files[:5]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            if "from typing import" in content or "->" in content:
                has_python_types = True
                break
        except Exception:
            pass

    # Check for test files (multi-language)
    skip = {"node_modules", ".git", "__pycache__", "dist", "build", ".venv", "venv"}
    test_patterns = [
        "*.test.ts",
        "*.test.js",
        "*.spec.ts",
        "*.spec.js",  # JS/TS
        "*_test.py",
        "test_*.py",  # Python
        "*_test.go",  # Go
        "*Test.java",
        "*Tests.java",
        "*IT.java",  # Java
    ]
    test_count = 0
    for pattern in test_patterns:
        for p in repo.rglob(pattern):
            parts = p.relative_to(repo).parts
            if not any(part in skip for part in parts):
                test_count += 1

    # Check for CI
    has_ci = (repo / ".github" / "workflows").is_dir() or (repo / ".gitlab-ci.yml").exists()

    # Check for quality tools
    has_sonar = (repo / "sonar-project.properties").exists()
    has_codecov = (repo / ".codecov.yml").exists() or (repo / "codecov.yml").exists()

    # IDE settings
    has_vscode_settings = (repo / ".vscode" / "settings.json").exists()

    safety_score = 0
    if has_typescript or has_python_types:
        safety_score += 3
    if test_count > 10:
        safety_score += 3
    elif test_count > 0:
        safety_score += 1
    if has_ci:
        safety_score += 2
    if has_sonar or has_codecov:
        safety_score += 2

    return {
        "has_type_system": has_typescript or has_python_types,
        "test_file_count": test_count,
        "has_ci": has_ci,
        "has_sonar": has_sonar,
        "has_codecov": has_codecov,
        "has_vscode_settings": has_vscode_settings,
        "safety_score": safety_score,
        "safety_level": ("high" if safety_score >= 7 else "medium" if safety_score >= 4 else "low"),
    }
