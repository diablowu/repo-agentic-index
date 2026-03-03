"""
Dimension-specific AutoGen evaluation agents (autogen-agentchat 0.7.x API).

Each agent class wraps an AssistantAgent configured for one dimension (D1-D5).
Tools (skills) are Python functions passed directly to the AssistantAgent.
Conversations run via asyncio (agent.run() is a coroutine).

Architecture:
    AssistantAgent(name, model_client, tools=[...], system_message=...)
    Tools are executed automatically by the agent (no separate executor needed)
    agent.run(task=...) returns TaskResult with message history
"""

import asyncio
import json
import re

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import TaskResult
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from rich.console import Console

from ..config import get_model_client
from ..skills import (
    analyze_directory_structure,
    # Git analyzer
    analyze_git_history,
    check_adr_records,
    check_build_scripts,
    check_ci_config,
    check_dependency_transparency,
    check_design_patterns,
    check_devcontainer,
    check_env_config,
    check_error_handling,
    check_extensibility,
    check_file_exists,
    check_gitignore,
    # Language-specific analyzer (Go / Java / Vue / SQL)
    check_go_module,
    check_inline_documentation,
    check_java_build,
    check_lint_config,
    check_logging_config,
    check_module_interfaces,
    check_naming_consistency,
    check_refactoring_safety,
    check_schema_validation,
    check_sql_migrations,
    # Code analyzer
    check_type_annotations,
    check_vue_components,
    count_test_files,
    list_files_by_extension,
    read_file_content,
    # File scanner
    scan_repository,
)

_verbose_console = Console(highlight=False)

# Agent tag color map
_TAG_COLORS = {
    "D1_ContextAgent": "cyan",
    "D2_SDDAgent": "blue",
    "D3_BoundaryAgent": "yellow",
    "D4_ExecutabilityAgent": "magenta",
    "D5_EvolutionAgent": "green",
    "SummaryAgent": "white",
    "ImprovementAgent": "bright_cyan",
}


def _print_verbose_event(tag: str, event) -> None:
    """Print a single AutoGen stream event with agent tag."""
    color = _TAG_COLORS.get(tag, "white")
    prefix = f"[{color}][{tag}][/{color}]"
    msg_type = type(event).__name__

    if msg_type == "ToolCallRequestEvent":
        for call in event.content:
            try:
                args_obj = (
                    json.loads(call.arguments)
                    if isinstance(call.arguments, str)
                    else call.arguments
                )
                args_str = json.dumps(args_obj, ensure_ascii=False)
            except Exception:
                args_str = str(call.arguments)
            args_display = args_str[:120] + "…" if len(args_str) > 120 else args_str
            _verbose_console.print(
                f"  {prefix} [yellow]⚙ Tool →[/yellow] [bold]{call.name}[/bold]({args_display})"
            )

    elif msg_type == "ToolCallExecutionEvent":
        for result in event.content:
            result_str = str(result.content)
            display = result_str[:200] + "…" if len(result_str) > 200 else result_str
            _verbose_console.print(f"  {prefix} [green]✓ Result →[/green] {display}")

    elif msg_type == "TextMessage":
        content = re.sub(r"<think>.*?</think>", "[思考已隐藏]", str(event.content), flags=re.DOTALL)
        display = content[:400] + "…" if len(content) > 400 else content
        _verbose_console.print(f"  {prefix} [bold]LLM ↩[/bold] {display}")

    # ToolCallSummaryMessage skipped (redundant with execution events)


# ─── JSON Extraction ──────────────────────────────────────────────────────────


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from LLM output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_evaluation_json(task_result) -> dict | None:
    """Extract the structured evaluation JSON from the agent's task result."""
    for msg in reversed(task_result.messages):
        content = getattr(msg, "content", None)
        if not content or not isinstance(content, str):
            continue
        content = _strip_think_tags(content)

        # Strategy 1: Extract everything between ```json and ```
        match = re.search(r"```json\s*(.+?)```", content, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
            try:
                data = json.loads(json_str)
                if isinstance(data, dict) and "dimension" in data:
                    return data
            except json.JSONDecodeError:
                pass

        # Strategy 2: Find JSON by locating the outermost braces
        start = content.find('{"dimension"')
        if start >= 0:
            # Walk forward counting braces to find the matching close brace
            depth = 0
            end = start
            for i, ch in enumerate(content[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > start:
                try:
                    data = json.loads(content[start:end])
                    if isinstance(data, dict) and "dimension" in data:
                        return data
                except json.JSONDecodeError:
                    pass

    return None


def _run_agent_async(
    agent: AssistantAgent, task: str, verbose: bool = False, tag: str = "AGENT"
) -> dict | None:
    """
    Execute the agent evaluation using a single-agent RoundRobinGroupChat team.

    Note: TextMentionTermination can accidentally trigger on the task message itself
    if it contains the stop phrase, so we use MaxMessageTermination only.
    The agent will naturally stop after completing its evaluation.
    """
    # Use MaxMessageTermination: tool calls + tool results + evaluation response
    # Each tool call round takes 2 messages (request + result), plus final text
    # 14 messages allows ~6 tool calls with reflection
    termination = MaxMessageTermination(14)
    color = _TAG_COLORS.get(tag, "white")

    async def _inner():
        team = RoundRobinGroupChat(
            participants=[agent],
            termination_condition=termination,
        )
        if verbose:
            _verbose_console.rule(f"[{color}][{tag}] 开始评估[/{color}]")
            final: TaskResult | None = None
            async for event in team.run_stream(task=task):
                if isinstance(event, TaskResult):
                    final = event
                else:
                    _print_verbose_event(tag, event)
            if final:
                _verbose_console.rule(f"[{color}][{tag}] 评估完成[/{color}]")
            return _extract_evaluation_json(final) if final else None
        else:
            result = await team.run(task=task)
            return _extract_evaluation_json(result)

    try:
        return asyncio.run(_inner())
    except RuntimeError:
        # Fallback for nested event loops (e.g. Jupyter)
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, _inner())
            return future.result()


# ─── D1 — Context Comprehensibility ──────────────────────────────────────────

D1_SYSTEM_PROMPT = """你是一位专业的代码仓库评估专家，负责评估仓库的「D1 — 上下文可理解性（Context Comprehensibility）」维度（权重30%）。

## 评估任务

对以下5个子项逐一评分（每项0-10分，总分50分）：
1. **1.1 项目全局描述文档**：README完整度、ARCHITECTURE.md、架构图、Glossary、文档同步性
2. **1.2 目录结构清晰度**：语义化命名、合理层次(3-5层)、目录说明文档
3. **1.3 命名规范一致性**：ESLint/Ruff命名规则、文件/类/变量命名统一性、自解释性
4. **1.4 内联文档与注释质量**：JSDoc/docstring覆盖、Why注释、模块头说明、TODO规范
5. **1.5 依赖关系透明度**：锁文件、显式import/DI、循环依赖检测、依赖选型文档

## 工作流程

1. 调用工具收集仓库信息（文件存在性、目录结构、命名规范、注释质量、依赖管理）
2. 基于收集的数据，对每个子项给出0-10分和评分理由
3. 计算总分（total=各项之和）和百分制（percentage=total/50*100）和加权得分（weighted_score=percentage*0.30）
4. 输出结构化JSON结果，最后写 EVALUATION_COMPLETE

## 输出格式（必须包含以下JSON代码块）

```json
{
  "dimension": "D1",
  "name": "上下文可理解性",
  "weight": 0.30,
  "items": [
    {"id": "1.1", "name": "项目全局描述文档", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "1.2", "name": "目录结构清晰度", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "1.3", "name": "命名规范一致性", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "1.4", "name": "内联文档与注释质量", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "1.5", "name": "依赖关系透明度", "score": 0, "max_score": 10, "reasoning": ""}
  ],
  "total": 0,
  "max_total": 50,
  "percentage": 0.0,
  "weighted_score": 0.0
}
```

EVALUATION_COMPLETE
"""

D1_TOOLS = [
    scan_repository,
    check_file_exists,
    analyze_directory_structure,
    check_naming_consistency,
    check_inline_documentation,
    check_dependency_transparency,
    list_files_by_extension,
    # Multi-language support
    check_go_module,
    check_java_build,
    check_vue_components,
]


class D1ContextAgent:
    """Agent evaluating D1 — Context Comprehensibility (30% weight)."""

    def evaluate(self, repo_path: str, verbose: bool = False) -> dict | None:
        agent = AssistantAgent(
            name="D1_ContextAgent",
            model_client=get_model_client(),
            tools=D1_TOOLS,
            system_message=D1_SYSTEM_PROMPT,
            reflect_on_tool_use=True,
            max_tool_iterations=8,
        )
        task = (
            f"请评估位于 `{repo_path}` 的代码仓库的 D1 — 上下文可理解性维度。\n"
            "请调用工具收集仓库信息后给出评分，最后输出JSON结果。"
        )
        return _run_agent_async(agent, task, verbose=verbose, tag="D1_ContextAgent")


# ─── D2 — Specification-Driven Development ───────────────────────────────────

D2_SYSTEM_PROMPT = """你是一位专业的代码仓库评估专家，负责评估仓库的「D2 — 规约驱动能力（SDD）」维度（权重30%，与D1并列最高权重）。

## 评估任务

对以下5个子项逐一评分（每项0-10分，总分50分）：
1. **2.1 类型系统完备性**：TypeScript strict/Pydantic/类型覆盖率>95%/any使用率<1%/类型集中管理
2. **2.2 接口契约定义**：OpenAPI 3.x/GraphQL Schema/Protobuf/请求响应示例/错误码枚举/版本管理
3. **2.3 数据校验与Schema定义**：Zod/Pydantic/JSON Schema/校验类型同源(z.infer)/结构化错误/迁移机制
4. **2.4 模块接口边界**：Interface/Abstract Class/DI容器/barrel exports(index.ts)/Mock支持
5. **2.5 配置规约与环境管理**：.env.example/Schema校验(envalid)/多环境profile/敏感配置分离

## 工作流程

1. 调用工具收集类型系统、接口定义、Schema验证、模块边界、配置管理信息
2. 基于数据评分（total=各项之和，percentage=total/50*100，weighted_score=percentage*0.30）
3. 输出JSON结果和 EVALUATION_COMPLETE

## 输出格式

```json
{
  "dimension": "D2",
  "name": "规约驱动能力 (SDD)",
  "weight": 0.30,
  "items": [
    {"id": "2.1", "name": "类型系统完备性", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "2.2", "name": "接口契约定义", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "2.3", "name": "数据校验与Schema定义", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "2.4", "name": "模块接口边界", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "2.5", "name": "配置规约与环境管理", "score": 0, "max_score": 10, "reasoning": ""}
  ],
  "total": 0,
  "max_total": 50,
  "percentage": 0.0,
  "weighted_score": 0.0
}
```

EVALUATION_COMPLETE
"""

D2_TOOLS = [
    check_type_annotations,
    check_file_exists,
    check_schema_validation,
    check_module_interfaces,
    check_env_config,
    list_files_by_extension,
    # Multi-language support
    check_go_module,
    check_java_build,
    check_vue_components,
    check_sql_migrations,
]


class D2SDDAgent:
    """Agent evaluating D2 — Specification-Driven Development (30% weight)."""

    def evaluate(self, repo_path: str, verbose: bool = False) -> dict | None:
        agent = AssistantAgent(
            name="D2_SDDAgent",
            model_client=get_model_client(),
            tools=D2_TOOLS,
            system_message=D2_SYSTEM_PROMPT,
            reflect_on_tool_use=True,
            max_tool_iterations=8,
        )
        task = (
            f"请评估位于 `{repo_path}` 的代码仓库的 D2 — 规约驱动能力(SDD)维度。\n"
            "请调用工具收集类型系统、接口定义、Schema验证等信息后给出评分，最后输出JSON结果。"
        )
        return _run_agent_async(agent, task, verbose=verbose, tag="D2_SDDAgent")


# ─── D3 — Boundary Control & Guardrails ──────────────────────────────────────

D3_SYSTEM_PROMPT = """你是一位专业的代码仓库评估专家，负责评估仓库的「D3 — 边界控制与安全护栏」维度（权重15%）。

## 评估任务

对以下5个子项逐一评分（每项0-10分，总分50分）：
1. **3.1 测试覆盖与验证机制**：单元测试>80%/集成测试/E2E/CI阻塞PR/测试<10min无flaky
2. **3.2 Lint/格式化强制约束**：ESLint/Prettier/Ruff/Black/pre-commit hook强制/CI检查/EditorConfig
3. **3.3 变更范围可控性**：Monorepo workspace/CODEOWNERS/影响分析(nx/turborepo)/DB迁移机制
4. **3.4 版本控制与回滚能力**：分支策略/Conventional Commits+commitlint/changelog自动生成/PR模板
5. **3.5 权限与安全模型**：Secret管理(Vault/KMS)/.gitignore完善/Secret扫描/最小权限

## 工作流程

1. 调用工具收集测试、CI、lint、git历史、gitignore、安全配置信息
2. 基于数据评分（total=各项之和，percentage=total/50*100，weighted_score=percentage*0.15）
3. 输出JSON结果和 EVALUATION_COMPLETE

## 输出格式

```json
{
  "dimension": "D3",
  "name": "边界控制与安全护栏",
  "weight": 0.15,
  "items": [
    {"id": "3.1", "name": "测试覆盖与验证机制", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "3.2", "name": "Lint/格式化强制约束", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "3.3", "name": "变更范围可控性", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "3.4", "name": "版本控制与回滚能力", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "3.5", "name": "权限与安全模型", "score": 0, "max_score": 10, "reasoning": ""}
  ],
  "total": 0,
  "max_total": 50,
  "percentage": 0.0,
  "weighted_score": 0.0
}
```

EVALUATION_COMPLETE
"""

D3_TOOLS = [
    count_test_files,
    check_ci_config,
    check_lint_config,
    analyze_git_history,
    check_gitignore,
    check_file_exists,
    # Multi-language support
    check_go_module,
    check_java_build,
]


class D3BoundaryAgent:
    """Agent evaluating D3 — Boundary Control & Guardrails (15% weight)."""

    def evaluate(self, repo_path: str, verbose: bool = False) -> dict | None:
        agent = AssistantAgent(
            name="D3_BoundaryAgent",
            model_client=get_model_client(),
            tools=D3_TOOLS,
            system_message=D3_SYSTEM_PROMPT,
            reflect_on_tool_use=True,
            max_tool_iterations=8,
        )
        task = (
            f"请评估位于 `{repo_path}` 的代码仓库的 D3 — 边界控制与安全护栏维度。\n"
            "请调用工具收集测试、CI、lint、版本控制、安全配置信息后给出评分，最后输出JSON结果。"
        )
        return _run_agent_async(agent, task, verbose=verbose, tag="D3_BoundaryAgent")


# ─── D4 — Task Executability ──────────────────────────────────────────────────

D4_SYSTEM_PROMPT = """你是一位专业的代码仓库评估专家，负责评估仓库的「D4 — 任务可执行性」维度（权重15%）。

## 评估任务

对以下5个子项逐一评分（每项0-10分，总分50分）：
1. **4.1 构建与运行便捷性**：一键构建(make dev/docker compose up)/<5min就绪/devcontainer/依赖自动化
2. **4.2 错误反馈质量**：自定义错误类型(ErrorCode枚举)/上下文信息/建议修复/结构化JSON日志+traceId
3. **4.3 脚本与自动化工具**：Makefile/Taskfile覆盖所有操作/help命令/幂等脚本/代码生成器
4. **4.4 可调试与可观测性**：launch.json/结构化日志框架/分布式tracing/health端点+metrics
5. **4.5 增量构建与热重载**：HMR/增量编译/<3s反馈/模块级部分构建/文件监听稳定

## 工作流程

1. 调用工具收集构建脚本、错误处理、日志配置、调试配置信息
2. 基于数据评分（total=各项之和，percentage=total/50*100，weighted_score=percentage*0.15）
3. 输出JSON结果和 EVALUATION_COMPLETE

## 输出格式

```json
{
  "dimension": "D4",
  "name": "任务可执行性",
  "weight": 0.15,
  "items": [
    {"id": "4.1", "name": "构建与运行便捷性", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "4.2", "name": "错误反馈质量", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "4.3", "name": "脚本与自动化工具", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "4.4", "name": "可调试与可观测性", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "4.5", "name": "增量构建与热重载", "score": 0, "max_score": 10, "reasoning": ""}
  ],
  "total": 0,
  "max_total": 50,
  "percentage": 0.0,
  "weighted_score": 0.0
}
```

EVALUATION_COMPLETE
"""

D4_TOOLS = [
    check_build_scripts,
    check_file_exists,
    check_error_handling,
    check_logging_config,
    check_devcontainer,
    list_files_by_extension,
    # Multi-language support
    check_go_module,
    check_java_build,
    check_sql_migrations,
]


class D4ExecutabilityAgent:
    """Agent evaluating D4 — Task Executability (15% weight)."""

    def evaluate(self, repo_path: str, verbose: bool = False) -> dict | None:
        agent = AssistantAgent(
            name="D4_ExecutabilityAgent",
            model_client=get_model_client(),
            tools=D4_TOOLS,
            system_message=D4_SYSTEM_PROMPT,
            reflect_on_tool_use=True,
            max_tool_iterations=8,
        )
        task = (
            f"请评估位于 `{repo_path}` 的代码仓库的 D4 — 任务可执行性维度。\n"
            "请调用工具收集构建脚本、错误处理、日志、调试配置信息后给出评分，最后输出JSON结果。"
        )
        return _run_agent_async(agent, task, verbose=verbose, tag="D4_ExecutabilityAgent")


# ─── D5 — Evolution Friendliness ─────────────────────────────────────────────

D5_SYSTEM_PROMPT = """你是一位专业的代码仓库评估专家，负责评估仓库的「D5 — 演进友好性」维度（权重10%）。

## 评估任务

对以下5个子项逐一评分（每项0-10分，总分50分）：
1. **5.1 设计模式一致性**：ADR目录/统一分层(Controller-Service-Repository)/代码模板生成器/错误处理模式统一
2. **5.2 可扩展性设计**：插件/中间件/Hook机制/OCP原则(新增仅加文件)/策略/工厂模式替代if-else
3. **5.3 知识库与决策记录**：CLAUDE.md/CONTRIBUTING.md/ADR目录/Troubleshooting文档/最佳实践指南
4. **5.4 重构安全网**：类型+测试+CI三重保障/IDE重构兼容/重构指南/代码度量工具(SonarQube)
5. **5.5 Agent专属指引文件**：CLAUDE.md/.cursorrules/copilot-instructions/项目约定+禁止操作+代码模板+常用命令

## 工作流程

1. 调用工具收集设计模式、知识库文件、Agent指引、重构安全网信息
2. 基于数据评分（total=各项之和，percentage=total/50*100，weighted_score=percentage*0.10）
3. 输出JSON结果和 EVALUATION_COMPLETE

## 输出格式

```json
{
  "dimension": "D5",
  "name": "演进友好性",
  "weight": 0.10,
  "items": [
    {"id": "5.1", "name": "设计模式一致性", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "5.2", "name": "可扩展性设计", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "5.3", "name": "知识库与决策记录", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "5.4", "name": "重构安全网", "score": 0, "max_score": 10, "reasoning": ""},
    {"id": "5.5", "name": "Agent专属指引文件", "score": 0, "max_score": 10, "reasoning": ""}
  ],
  "total": 0,
  "max_total": 50,
  "percentage": 0.0,
  "weighted_score": 0.0
}
```

EVALUATION_COMPLETE
"""

D5_TOOLS = [
    check_adr_records,
    check_file_exists,
    check_design_patterns,
    check_extensibility,
    check_refactoring_safety,
    read_file_content,
    # Multi-language support
    count_test_files,
    check_go_module,
    check_java_build,
]


class D5EvolutionAgent:
    """Agent evaluating D5 — Evolution Friendliness (10% weight)."""

    def evaluate(self, repo_path: str, verbose: bool = False) -> dict | None:
        agent = AssistantAgent(
            name="D5_EvolutionAgent",
            model_client=get_model_client(),
            tools=D5_TOOLS,
            system_message=D5_SYSTEM_PROMPT,
            reflect_on_tool_use=True,
            max_tool_iterations=8,
        )
        task = (
            f"请评估位于 `{repo_path}` 的代码仓库的 D5 — 演进友好性维度。\n"
            "请调用工具收集设计模式、知识库文件、Agent指引信息后给出评分，最后输出JSON结果。"
        )
        return _run_agent_async(agent, task, verbose=verbose, tag="D5_EvolutionAgent")
