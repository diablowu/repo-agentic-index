"""
Language-specific analysis skills for Go, Java, Vue, and SQL.

Supplements code_analyzer.py with language-specific detection
that the generic TypeScript/Python-focused analyzers cannot cover.
"""

import json
import re
from pathlib import Path

from .file_scanner import _resolve, list_files_by_extension


# ─── Go ───────────────────────────────────────────────────────────────────────


def check_go_module() -> dict:
    """
    Analyze Go module configuration and Go-specific code quality patterns.

    Checks go.mod, interface definitions, test coverage, error handling patterns,
    linter configuration, and Go idiom usage.
    """
    repo = _resolve()

    # go.mod analysis
    gomod_path = repo / "go.mod"
    gomod_info = {"exists": False}
    if gomod_path.exists():
        content = gomod_path.read_text(encoding="utf-8", errors="replace")
        module_match = re.search(r"^module\s+(\S+)", content, re.MULTILINE)
        go_version_match = re.search(r"^go\s+([\d.]+)", content, re.MULTILINE)
        requires = re.findall(r"^\s+(\S+)\s+(v[\d.]+)", content, re.MULTILINE)
        gomod_info = {
            "exists": True,
            "module_name": module_match.group(1) if module_match else "unknown",
            "go_version": go_version_match.group(1) if go_version_match else "unknown",
            "dependency_count": len(requires),
            "has_go_sum": (repo / "go.sum").exists(),
        }

    # Count Go source files vs test files
    go_files = list_files_by_extension("go")["files"]
    test_files = [f for f in go_files if f.endswith("_test.go")]
    source_files = [f for f in go_files if not f.endswith("_test.go")]

    # Analyze Go source for interfaces, error patterns, context usage
    interface_count = 0
    error_wrapping = 0   # fmt.Errorf with %w / errors.Is / errors.As
    context_usage = 0
    godoc_count = 0      # exported symbols with doc comments

    for f in source_files[:30]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            interface_count += len(re.findall(r'\btype\s+\w+\s+interface\s*\{', content))
            error_wrapping += len(re.findall(r'fmt\.Errorf\([^)]*%w|errors\.Is\(|errors\.As\(', content))
            context_usage += len(re.findall(r'\bcontext\.Context\b|\bctx\s+context\.Context', content))
            # Exported funcs/types with preceding // comment
            godoc_count += len(re.findall(r'//[^\n]+\n(?:func|type|var|const)\s+[A-Z]', content))
        except Exception:
            pass

    # Linter configuration
    lint_configs = {
        "golangci_lint": any([
            (repo / ".golangci.yml").exists(),
            (repo / ".golangci.yaml").exists(),
            (repo / ".golangci.toml").exists(),
            (repo / ".golangci.json").exists(),
        ]),
        "staticcheck": any(repo.rglob("staticcheck.conf")),
        "go_vet": True,  # built-in, always available
        "gofmt": True,   # built-in
    }

    # Check Makefile/CI for Go-specific commands
    go_tooling = {
        "has_go_generate": any(
            "go:generate" in (repo / f).read_text(encoding="utf-8", errors="replace")
            for f in source_files[:20]
            if (repo / f).exists()
        ),
        "has_go_embed": any(
            "//go:embed" in (repo / f).read_text(encoding="utf-8", errors="replace")
            for f in source_files[:20]
            if (repo / f).exists()
        ),
    }

    test_ratio = round(len(test_files) / max(len(source_files), 1), 2)

    return {
        "go_mod": gomod_info,
        "source_files": len(source_files),
        "test_files": len(test_files),
        "test_to_source_ratio": test_ratio,
        "interface_count": interface_count,
        "error_wrapping_count": error_wrapping,
        "context_usage_count": context_usage,
        "godoc_comment_count": godoc_count,
        "lint_configs": lint_configs,
        "has_linter": lint_configs["golangci_lint"] or lint_configs["staticcheck"],
        "go_tooling": go_tooling,
        "quality_summary": {
            "has_tests": len(test_files) > 0,
            "has_interfaces": interface_count > 0,
            "uses_error_wrapping": error_wrapping > 0,
            "has_linter_config": lint_configs["golangci_lint"],
        },
    }


# ─── Java ─────────────────────────────────────────────────────────────────────


def check_java_build() -> dict:
    """
    Analyze Java/JVM project build system and quality tooling.

    Detects Maven/Gradle, test frameworks, static analysis tools,
    and common frameworks (Spring Boot, Quarkus, Micronaut).
    """
    repo = _resolve()

    # Build system detection
    has_maven = (repo / "pom.xml").exists()
    has_gradle = any([
        (repo / "build.gradle").exists(),
        (repo / "build.gradle.kts").exists(),
    ])
    has_wrapper = (repo / "mvnw").exists() or (repo / "gradlew").exists()

    build_info = {
        "maven": has_maven,
        "gradle": has_gradle,
        "has_wrapper": has_wrapper,
        "build_system": "maven" if has_maven else "gradle" if has_gradle else "none",
    }

    # Parse pom.xml for framework/tool detection
    frameworks = {
        "spring_boot": False,
        "quarkus": False,
        "micronaut": False,
        "jakarta_ee": False,
        "lombok": False,
    }
    test_frameworks = {
        "junit5": False,
        "junit4": False,
        "testng": False,
        "mockito": False,
        "assertj": False,
    }
    lint_tools = {
        "checkstyle": False,
        "pmd": False,
        "spotbugs": False,
        "sonarlint": False,
        "errorprone": False,
    }

    build_content = ""
    if has_maven:
        try:
            build_content = (repo / "pom.xml").read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    elif has_gradle:
        for f in ["build.gradle", "build.gradle.kts"]:
            p = repo / f
            if p.exists():
                try:
                    build_content = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
                break

    if build_content:
        bc = build_content.lower()
        frameworks["spring_boot"] = "spring-boot" in bc or "springframework.boot" in bc
        frameworks["quarkus"] = "quarkus" in bc
        frameworks["micronaut"] = "micronaut" in bc
        frameworks["jakarta_ee"] = "jakarta.ee" in bc or "javax" in bc
        frameworks["lombok"] = "lombok" in bc

        test_frameworks["junit5"] = "junit-jupiter" in bc or "junit5" in bc
        test_frameworks["junit4"] = "junit:junit" in bc or "junit4" in bc
        test_frameworks["testng"] = "testng" in bc
        test_frameworks["mockito"] = "mockito" in bc
        test_frameworks["assertj"] = "assertj" in bc

        lint_tools["checkstyle"] = "checkstyle" in bc
        lint_tools["pmd"] = "pmd" in bc
        lint_tools["spotbugs"] = "spotbugs" in bc or "findbugs" in bc
        lint_tools["errorprone"] = "error_prone" in bc or "errorprone" in bc

    # Count Java files and test files
    java_files = list_files_by_extension("java")["files"]
    test_java_files = [
        f for f in java_files
        if any(kw in f for kw in ["Test.java", "Tests.java", "IT.java", "Spec.java", "/test/"])
    ]

    # Check code style config files
    has_checkstyle_xml = any(repo.rglob("checkstyle*.xml"))
    has_pmd_xml = any(repo.rglob("pmd*.xml"))
    has_editorconfig = (repo / ".editorconfig").exists()

    return {
        "build": build_info,
        "java_files": len(java_files),
        "test_files": len(test_java_files),
        "test_to_source_ratio": round(len(test_java_files) / max(len(java_files), 1), 2),
        "frameworks": frameworks,
        "active_frameworks": [k for k, v in frameworks.items() if v],
        "test_frameworks": test_frameworks,
        "active_test_frameworks": [k for k, v in test_frameworks.items() if v],
        "lint_tools": lint_tools,
        "active_lint_tools": [k for k, v in lint_tools.items() if v],
        "has_any_lint": any(lint_tools.values()),
        "has_checkstyle_config": has_checkstyle_xml,
        "has_pmd_config": has_pmd_xml,
        "has_editorconfig": has_editorconfig,
        "quality_summary": {
            "has_build_system": has_maven or has_gradle,
            "has_tests": len(test_java_files) > 0,
            "has_linter": any(lint_tools.values()),
            "has_framework": any(frameworks.values()),
        },
    }


# ─── Vue ──────────────────────────────────────────────────────────────────────


def check_vue_components() -> dict:
    """
    Analyze Vue.js project structure and component quality.

    Checks Composition API vs Options API usage, TypeScript integration,
    state management, linting, and testing setup.
    """
    repo = _resolve()

    vue_files = list_files_by_extension("vue")["files"]
    if not vue_files:
        return {
            "is_vue_project": False,
            "vue_file_count": 0,
            "message": "No .vue files found",
        }

    # Composition API vs Options API
    composition_count = 0
    options_count = 0
    script_setup_count = 0     # <script setup> — modern Vue 3
    typescript_sfc_count = 0   # <script lang="ts">
    has_props_define = 0       # defineProps / defineEmits

    for f in vue_files[:40]:
        try:
            content = (repo / f).read_text(encoding="utf-8", errors="replace")
            if "setup()" in content or "<script setup" in content:
                composition_count += 1
            if "export default {" in content and "setup()" not in content:
                options_count += 1
            if "<script setup" in content:
                script_setup_count += 1
            if 'lang="ts"' in content or "lang='ts'" in content:
                typescript_sfc_count += 1
            if "defineProps" in content or "defineEmits" in content:
                has_props_define += 1
        except Exception:
            pass

    # State management
    pkg_json = repo / "package.json"
    state_tools = {"pinia": False, "vuex": False}
    test_tools = {"vitest": False, "vue_test_utils": False, "cypress": False}
    lint_tools = {"eslint_plugin_vue": False, "volar": False, "vue_tsc": False}

    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            all_deps = {
                **data.get("dependencies", {}),
                **data.get("devDependencies", {}),
            }
            dep_str = json.dumps(all_deps).lower()

            state_tools["pinia"] = "pinia" in dep_str
            state_tools["vuex"] = "vuex" in dep_str
            test_tools["vitest"] = "vitest" in dep_str
            test_tools["vue_test_utils"] = "@vue/test-utils" in dep_str
            test_tools["cypress"] = "cypress" in dep_str
            lint_tools["eslint_plugin_vue"] = "eslint-plugin-vue" in dep_str
            lint_tools["volar"] = "@vue/language-tools" in dep_str or "volar" in dep_str
            lint_tools["vue_tsc"] = "vue-tsc" in dep_str
        except Exception:
            pass

    # vue.config or vite.config
    has_vite = any((repo / f).exists() for f in ["vite.config.ts", "vite.config.js"])
    has_vue_config = (repo / "vue.config.js").exists() or (repo / "vue.config.ts").exists()

    total = max(len(vue_files), 1)
    return {
        "is_vue_project": True,
        "vue_file_count": len(vue_files),
        "composition_api_count": composition_count,
        "options_api_count": options_count,
        "script_setup_count": script_setup_count,
        "typescript_sfc_count": typescript_sfc_count,
        "defineprops_count": has_props_define,
        "composition_ratio": round(composition_count / total, 2),
        "typescript_ratio": round(typescript_sfc_count / total, 2),
        "state_management": state_tools,
        "test_tools": test_tools,
        "lint_tools": lint_tools,
        "has_any_lint": any(lint_tools.values()),
        "has_any_test": any(test_tools.values()),
        "has_vite": has_vite,
        "has_vue_config": has_vue_config,
        "api_style": (
            "Composition API (script setup)" if script_setup_count > total * 0.5 else
            "Composition API" if composition_count > options_count else
            "Options API"
        ),
        "quality_summary": {
            "uses_typescript": typescript_sfc_count > total * 0.5,
            "has_lint": lint_tools["eslint_plugin_vue"],
            "has_type_check": lint_tools["vue_tsc"],
            "has_state_mgmt": any(state_tools.values()),
        },
    }


# ─── SQL / Database ───────────────────────────────────────────────────────────


def check_sql_migrations() -> dict:
    """
    Detect SQL schema management, migration tooling, and ORM usage.

    Checks for migration directories, ORM frameworks, migration tools
    (Flyway, Liquibase, Alembic, golang-migrate), and schema files.
    """
    repo = _resolve()

    # Migration directories
    migration_dirs = [
        "migrations", "migration", "db/migrations", "database/migrations",
        "src/migrations", "sql/migrations", "flyway", "liquibase",
        "alembic/versions", "db/migrate",
    ]
    found_migration_dirs = [d for d in migration_dirs if (repo / d).is_dir()]

    # Count SQL files
    sql_files = list_files_by_extension("sql")["files"]

    # ORM detection
    orm_tools = {
        # Go
        "gorm": False,
        "sqlx": False,
        "ent": False,
        "bun": False,
        # Java
        "hibernate": False,
        "mybatis": False,
        "jooq": False,
        # JS/TS
        "typeorm": False,
        "prisma": False,
        "drizzle": False,
        "sequelize": False,
        "knex": False,
        # Python
        "sqlalchemy": False,
        "tortoise": False,
        "peewee": False,
    }

    # Migration tools
    migration_tools = {
        "flyway": False,
        "liquibase": False,
        "alembic": False,
        "golang_migrate": False,
        "goose": False,
        "atlas": False,
        "dbmate": False,
    }

    # Check go.mod for Go ORM/migration tools
    gomod = repo / "go.mod"
    if gomod.exists():
        content = gomod.read_text(encoding="utf-8", errors="replace").lower()
        orm_tools["gorm"] = "gorm.io/gorm" in content
        orm_tools["sqlx"] = "jmoiron/sqlx" in content
        orm_tools["ent"] = "entgo.io/ent" in content
        orm_tools["bun"] = "uptrace/bun" in content
        migration_tools["golang_migrate"] = "golang-migrate" in content
        migration_tools["goose"] = "pressly/goose" in content or "goose" in content
        migration_tools["atlas"] = "ariga.io/atlas" in content

    # Check package.json for JS ORM/migration tools
    pkg_json = repo / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
            all_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            deps_str = json.dumps(all_deps).lower()
            orm_tools["typeorm"] = "typeorm" in deps_str
            orm_tools["prisma"] = "prisma" in deps_str
            orm_tools["drizzle"] = "drizzle-orm" in deps_str
            orm_tools["sequelize"] = "sequelize" in deps_str
            orm_tools["knex"] = "knex" in deps_str
        except Exception:
            pass

    # Check Python requirements for ORM/migration tools
    for req_file in ["requirements.txt", "pyproject.toml", "Pipfile"]:
        p = repo / req_file
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace").lower()
            orm_tools["sqlalchemy"] = "sqlalchemy" in content
            orm_tools["tortoise"] = "tortoise-orm" in content
            orm_tools["peewee"] = "peewee" in content
            migration_tools["alembic"] = "alembic" in content

    # Check pom.xml/build.gradle for Java ORM
    for build_file in ["pom.xml", "build.gradle", "build.gradle.kts"]:
        p = repo / build_file
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace").lower()
            orm_tools["hibernate"] = "hibernate" in content
            orm_tools["mybatis"] = "mybatis" in content
            orm_tools["jooq"] = "jooq" in content
            migration_tools["flyway"] = "flyway" in content
            migration_tools["liquibase"] = "liquibase" in content

    # Check for Prisma schema
    has_prisma_schema = any(repo.rglob("schema.prisma"))

    # Check for Atlas/DBMate config files
    migration_tools["atlas"] = migration_tools["atlas"] or (repo / "atlas.hcl").exists()
    migration_tools["dbmate"] = (repo / ".dbmate").exists()

    active_orms = [k for k, v in orm_tools.items() if v]
    active_migrations = [k for k, v in migration_tools.items() if v]

    return {
        "sql_files": len(sql_files),
        "migration_directories": found_migration_dirs,
        "has_migrations": bool(found_migration_dirs) or len(sql_files) > 0,
        "orm_tools": orm_tools,
        "active_orms": active_orms,
        "migration_tools": migration_tools,
        "active_migration_tools": active_migrations,
        "has_orm": bool(active_orms),
        "has_migration_tool": bool(active_migrations),
        "has_prisma_schema": has_prisma_schema,
        "quality_summary": {
            "has_schema_management": bool(found_migration_dirs) or has_prisma_schema,
            "has_orm": bool(active_orms),
            "has_migration_versioning": bool(active_migrations),
        },
    }
