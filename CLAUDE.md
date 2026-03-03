# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Agentic Evaluator** — 基于 AutoGen 多智能体框架的代码仓库「Agentic Coding 友好度」评估工具。根据 Repository Agentic-Readiness Scoring Framework v1.0，从 D1–D5 五个维度对目标仓库进行评分。

## Commands

```bash
# 安装依赖
uv sync

# 启动 Mock LLM 服务器（测试用，另开一个终端）
uv run mock-server

# 评估仓库（默认对接 Mock 服务器）
uv run evaluate /path/to/repo

# 使用真实 OpenAI 兼容接口评估
LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-... uv run evaluate /path/to/repo

# 保存 JSON 报告
uv run evaluate /path/to/repo --output report.json

# 检查 Mock 服务器是否运行
uv run evaluate check-server

# 运行测试
uv run pytest

# 运行单个测试文件
uv run pytest tests/test_xxx.py -v
```

## Architecture

### 评估流程

```
EvaluationOrchestrator.evaluate(repo_path)
  → set_repo_path()                   # 设置全局仓库路径
  → D1ContextAgent.evaluate()         # 上下文可理解性 (30%)
  → D2SDDAgent.evaluate()             # 规约驱动能力 (30%)
  → D3BoundaryAgent.evaluate()        # 边界控制与安全护栏 (15%)
  → D4ExecutabilityAgent.evaluate()   # 任务可执行性 (15%)
  → D5EvolutionAgent.evaluate()       # 演进友好性 (10%)
  → SummaryAgent.summarize()          # 生成综合报告
  → EvaluationReport                  # 返回最终报告
```

### 关键模块

- **`src/agentic_evaluator/agents/dimension_agents.py`** — D1–D5 五个维度 Agent，每个 Agent 接收特定的 tools 子集，通过 `_run_agent_async()` 运行，结果由 `_extract_evaluation_json()` 提取
- **`src/agentic_evaluator/agents/orchestrator.py`** — `EvaluationOrchestrator`（协调所有 Agent）、`SummaryAgent`（生成综合分析）、`EvaluationReport` / `DimensionResult` 数据类
- **`src/agentic_evaluator/skills/`** — 纯 Python 工具函数（无 AutoGen 依赖），直接传递给 `AssistantAgent(tools=[...])`
  - `file_scanner.py`：`scan_repository`, `check_file_exists`, `read_file_content` 等
  - `code_analyzer.py`：`check_type_annotations`, `check_lint_config`, `check_error_handling` 等
  - `git_analyzer.py`：`analyze_git_history`, `check_ci_config`, `count_test_files` 等
- **`src/agentic_evaluator/config.py`** — `get_model_client()` 返回 `OpenAIChatCompletionClient`，通过环境变量配置
- **`mock_server/server.py`** — FastAPI 实现的 OpenAI 兼容 Mock 服务器，用于本地测试

### AutoGen API 关键约束（autogen-agentchat 0.7.x）

- Import: `from autogen_agentchat.agents import AssistantAgent`
- `AssistantAgent.run()` **不接受** `termination_condition` 参数
- 必须用 `RoundRobinGroupChat([agent], termination_condition=...)` 包装才能设置终止条件
- 使用 `MaxMessageTermination(14)` — **不用** `TextMentionTermination`（会被 task 消息本身的文本触发）
- `OpenAIChatCompletionClient` 来自 `autogen_ext.models.openai`

### Agent 输出格式

每个维度 Agent 的 system prompt 要求 LLM 输出包含 `"dimension"` 键的 JSON 代码块，末尾写 `EVALUATION_COMPLETE`。`_extract_evaluation_json()` 用两种策略提取：
1. 正则匹配 ` ```json...``` ` 代码块
2. 从 `{"dimension"` 开始的括号计数回退策略

### 评分体系

- 每个维度 5 个子项，每项 0–10 分，总分 50 分
- `percentage = total / 50 * 100`，`weighted_score = percentage × weight`（由代码计算，不依赖 LLM）
- 最终总分 = 各维度 `weighted_score` 之和（满分 100）
- 等级：S(≥90) / A(≥75) / B(≥60) / C(≥40) / D(≥20) / F(<20)

---

## 各维度指标详解

### D1 — 上下文可理解性（权重 30%）

**Agent**: `D1ContextAgent`

| 子项 | 满分 | 评估依据 | 主要 Skills |
|------|------|---------|------------|
| 1.1 项目全局描述文档 | 10 | README 完整度、是否有 ARCHITECTURE.md、Glossary、文档同步性 | `check_file_exists("README.md")`, `scan_repository()` |
| 1.2 目录结构清晰度 | 10 | 语义化命名比例、目录层次深度（推荐 3-5 层）、是否有目录说明文档 | `analyze_directory_structure()` → `semantic_naming`, `avg_directory_depth`, `patterns` |
| 1.3 命名规范一致性 | 10 | 文件命名风格一致性比例（`consistency_ratio`）、是否有 ESLint/golangci naming rule | `check_naming_consistency()` → `dominant_style`, `consistency_ratio`, `has_naming_rule` |
| 1.4 内联文档与注释质量 | 10 | 注释密度（`comment_ratio`）、JSDoc/GoDoc/Javadoc 覆盖文件数、TODO 是否关联 issue | `check_inline_documentation()` → `comment_ratio`, `jsdoc_files`, `godoc_files`, `javadoc_files` |
| 1.5 依赖关系透明度 | 10 | 是否有锁文件（go.sum/package-lock/uv.lock）、是否有循环依赖检测、依赖选型文档 | `check_dependency_transparency()` → `lock_files`, `has_circular_dep_detection` |

**D1 工具列表**：`scan_repository`, `check_file_exists`, `analyze_directory_structure`, `check_naming_consistency`, `check_inline_documentation`, `check_dependency_transparency`, `list_files_by_extension`, `check_go_module`（GoDoc 统计）, `check_java_build`, `check_vue_components`

---

### D2 — 规约驱动能力 SDD（权重 30%）

**Agent**: `D2SDDAgent`

| 子项 | 满分 | 评估依据 | 主要 Skills |
|------|------|---------|------------|
| 2.1 类型系统完备性 | 10 | 主语言识别、TS strict 模式、Python Pydantic 覆盖率、Go interface 数量、Java 泛型/注解使用、Vue TS SFC 比例 | `check_type_annotations()` → `language`, `type_system`, `strict_mode`, `go_interface_count`, `typescript_sfc_count` |
| 2.2 接口契约定义 | 10 | OpenAPI/Protobuf/GraphQL 文件是否存在、Go interface 数量、Java 抽象类/接口、barrel exports | `check_module_interfaces()` → `typescript_interfaces`, `abstract_classes`；`check_go_module()` → `interface_count`；`check_file_exists("openapi.yml")` |
| 2.3 数据校验与 Schema 定义 | 10 | Zod/Joi/Pydantic/class-validator/go-playground/validator 使用情况、Prisma schema、schema 是否为 SSoT | `check_schema_validation()` → `schema_tools`, `has_any_validation`；`check_sql_migrations()` → `orm_tools` |
| 2.4 模块接口边界 | 10 | TS interface/abstract 数量、DI 容器（inversify/tsyringe）、Go package 边界、Java 抽象层、index.ts barrel exports | `check_module_interfaces()` → `di_container_usage`, `barrel_exports`；`check_go_module()` → `interface_count` |
| 2.5 配置规约与环境管理 | 10 | `.env.example` 是否存在、envalid/dotenv-safe 等配置 Schema 验证、多环境 profile 文件 | `check_env_config()` → `has_env_example`, `has_schema_validation`, `has_multi_env`, `env_example_quality` |

**D2 工具列表**：`check_type_annotations`, `check_file_exists`, `check_schema_validation`, `check_module_interfaces`, `check_env_config`, `list_files_by_extension`, `check_go_module`, `check_java_build`, `check_vue_components`, `check_sql_migrations`

---

### D3 — 边界控制与安全护栏（权重 15%）

**Agent**: `D3BoundaryAgent`

| 子项 | 满分 | 评估依据 | 主要 Skills |
|------|------|---------|------------|
| 3.1 测试覆盖与验证机制 | 10 | 测试文件总数（含 `*_test.go`/`*Test.java`）、CI 是否运行测试、是否有覆盖率配置、E2E/集成测试 | `count_test_files()` → `total_test_files`, `unit_tests`, `e2e_tests`, `active_test_frameworks`；`check_ci_config()` → `runs_tests_in_ci` |
| 3.2 Lint/格式化强制约束 | 10 | ESLint/Prettier/Ruff/Black/golangci-lint/Checkstyle 是否配置、pre-commit hook、CI 是否运行 lint | `check_lint_config()` → `configs`（含 `golangci_lint`, `checkstyle`, `pmd`）, `has_pre_commit_hooks`；`check_ci_config()` → `runs_lint_in_ci` |
| 3.3 变更范围可控性 | 10 | CODEOWNERS 是否存在、Monorepo 工具（nx/turborepo）、影响分析工具、DB 迁移机制 | `check_file_exists("CODEOWNERS")`；`check_go_module()` → `go_tooling` |
| 3.4 版本控制与回滚能力 | 10 | Conventional Commits 使用率（`conventional_commits_ratio`）、commitlint、PR 模板、CHANGELOG | `analyze_git_history()` → `conventional_commits_ratio`, `has_pr_template`, `has_changelog`, `has_commitlint` |
| 3.5 权限与安全模型 | 10 | `.gitignore` 关键模式（.env/node_modules/dist/*.key）完整性、secret 扫描工具（gitleaks）、`.env` 是否被 commit | `check_gitignore()` → `critical_patterns`, `missing_critical`, `env_file_committed`, `has_secret_scanning` |

**D3 工具列表**：`count_test_files`, `check_ci_config`, `check_lint_config`, `analyze_git_history`, `check_gitignore`, `check_file_exists`, `check_go_module`（lint_configs）, `check_java_build`（lint_tools）

---

### D4 — 任务可执行性（权重 15%）

**Agent**: `D4ExecutabilityAgent`

| 子项 | 满分 | 评估依据 | 主要 Skills |
|------|------|---------|------------|
| 4.1 构建与运行便捷性 | 10 | Makefile/Taskfile/npm scripts 覆盖 dev/build/test/lint 等操作、docker-compose、devcontainer、`operation_coverage` | `check_build_scripts()` → `covered_operations`, `operation_coverage`, `has_makefile`, `has_docker_compose`；`check_devcontainer()` |
| 4.2 错误反馈质量 | 10 | 自定义错误类/异常数量、ErrorCode 枚举、Go `%w` error wrapping 使用、Java `@ResponseStatus`、结构化错误响应 | `check_error_handling()` → `custom_error_classes`, `has_error_enum`, `go_error_wrapping_count`, `java_custom_exceptions`, `quality` |
| 4.3 脚本与自动化工具 | 10 | Makefile targets 列表、npm scripts 覆盖率、是否有 `help` 目标、代码生成器（plop/hygen）、Taskfile | `check_build_scripts()` → `make_targets`, `npm_scripts`, `has_help_target`, `has_taskfile` |
| 4.4 可调试与可观测性 | 10 | VS Code `launch.json` 是否存在、结构化日志（winston/pino/zap/zerolog）、OpenTelemetry、health 端点 | `check_logging_config()` → `logging_tools`, `has_vscode_debug`, `has_health_endpoint`, `has_tracing` |
| 4.5 增量构建与热重载 | 10 | HMR 支持、Go 原生增量编译（有则基础加分）、文件监听配置、反馈速度 | `check_build_scripts()` → `npm_scripts`（是否含 dev/watch）；`check_go_module()` → `go_mod.go_version` |

**D4 工具列表**：`check_build_scripts`, `check_file_exists`, `check_error_handling`, `check_logging_config`, `check_devcontainer`, `list_files_by_extension`, `check_go_module`, `check_java_build`, `check_sql_migrations`

---

### D5 — 演进友好性（权重 10%）

**Agent**: `D5EvolutionAgent`

| 子项 | 满分 | 评估依据 | 主要 Skills |
|------|------|---------|------------|
| 5.1 设计模式一致性 | 10 | ADR 目录是否存在及数量、统一分层（Controller-Service-Repository）、代码生成器（plop/hygen）、错误处理模式是否统一 | `check_adr_records()` → `has_adr`, `adr_count`；`check_design_patterns()` → `layered_patterns`, `layer_count`, `has_code_generators` |
| 5.2 可扩展性设计 | 10 | plugin/middleware 目录、Factory/Strategy/Hook 模式使用数量、大量 switch-case 反模式检测 | `check_extensibility()` → `has_plugin_dir`, `has_middleware`, `factory_pattern_count`, `strategy_pattern_count`, `hook_pattern_count`, `extensibility_score` |
| 5.3 知识库与决策记录 | 10 | CONTRIBUTING.md / ADR 目录 / CLAUDE.md / .cursorrules 存在性、Troubleshooting 文档 | `check_adr_records()` → `has_contributing`, `has_claude_md`, `has_cursorrules`；`read_file_content("CONTRIBUTING.md")` |
| 5.4 重构安全网 | 10 | 类型系统 + 测试文件总数 + CI 三重保障、SonarQube/Codecov 代码质量工具、`safety_score`（满分 10） | `check_refactoring_safety()` → `safety_score`, `safety_level`, `test_file_count`（含所有语言）, `has_ci`；`count_test_files()` |
| 5.5 Agent 专属指引文件 | 10 | CLAUDE.md / AGENTS.md / .cursorrules / copilot-instructions.md 文件内容质量、包含的约定/禁止操作/常用命令 | `check_file_exists("CLAUDE.md")`, `read_file_content("CLAUDE.md")`；`check_adr_records()` → `has_claude_md` |

**D5 工具列表**：`check_adr_records`, `check_file_exists`, `check_design_patterns`, `check_extensibility`, `check_refactoring_safety`, `read_file_content`, `count_test_files`, `check_go_module`, `check_java_build`

---

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_BASE_URL` | `http://localhost:8000/v1` | OpenAI 兼容 API 地址 |
| `LLM_API_KEY` | `mock-key-not-needed` | API 密钥 |
| `LLM_MODEL` | `mock-gpt-4` | 模型名称 |
