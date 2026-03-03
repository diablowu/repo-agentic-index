"""
Mock OpenAI-compatible LLM server for testing the Agentic Evaluator.

This server simulates an LLM that:
1. On first call per dimension: returns tool_calls to gather repo information
2. On subsequent calls (with tool results): returns structured evaluation JSON
"""

import json
import random
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Mock LLM Server", description="OpenAI-compatible mock LLM for testing")


# ─── Request/Response Models ──────────────────────────────────────────────────


class Message(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "gpt-4"
    messages: list[Message]
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None
    temperature: float = 0.7
    max_tokens: int | None = None


# ─── Dimension Detection ──────────────────────────────────────────────────────

DIMENSION_KEYWORDS = {
    "D1": ["上下文可理解性", "Context Comprehensibility", "D1", "README", "目录结构", "命名规范", "内联文档", "依赖关系"],
    "D2": ["规约驱动", "Specification-Driven", "D2", "SDD", "类型系统", "接口契约", "Schema", "配置规约"],
    "D3": ["边界控制", "Boundary Control", "D3", "测试覆盖", "Lint", "变更范围", "版本控制", "权限安全"],
    "D4": ["任务可执行性", "Task Executability", "D4", "构建", "错误反馈", "脚本", "调试", "热重载"],
    "D5": ["演进友好性", "Evolution Friendliness", "D5", "设计模式", "可扩展性", "知识库", "重构", "Agent指引"],
    "SUMMARY": ["汇总", "summary", "综合", "最终报告", "final report", "aggregate"],
}


def detect_dimension(messages: list[Message]) -> str:
    """Detect which dimension is being evaluated from message content."""
    system_content = ""
    for msg in messages:
        if msg.role == "system" and msg.content:
            system_content = msg.content
            break

    for dim, keywords in DIMENSION_KEYWORDS.items():
        for kw in keywords:
            if kw in system_content:
                return dim

    return "D1"  # Default


# ─── Tool Call Templates Per Dimension ───────────────────────────────────────

DIMENSION_TOOL_CALLS = {
    "D1": [
        {"name": "check_file_exists", "args": {"filename": "README.md"}},
        {"name": "check_file_exists", "args": {"filename": "ARCHITECTURE.md"}},
        {"name": "check_file_exists", "args": {"filename": "CONTRIBUTING.md"}},
        {"name": "analyze_directory_structure", "args": {}},
        {"name": "check_naming_consistency", "args": {}},
        {"name": "check_inline_documentation", "args": {}},
        {"name": "check_dependency_transparency", "args": {}},
    ],
    "D2": [
        {"name": "check_type_annotations", "args": {}},
        {"name": "check_file_exists", "args": {"filename": "openapi.yaml"}},
        {"name": "check_file_exists", "args": {"filename": "openapi.json"}},
        {"name": "check_schema_validation", "args": {}},
        {"name": "check_module_interfaces", "args": {}},
        {"name": "check_env_config", "args": {}},
    ],
    "D3": [
        {"name": "count_test_files", "args": {}},
        {"name": "check_ci_config", "args": {}},
        {"name": "check_lint_config", "args": {}},
        {"name": "check_file_exists", "args": {"filename": "CODEOWNERS"}},
        {"name": "analyze_git_history", "args": {}},
        {"name": "check_gitignore", "args": {}},
    ],
    "D4": [
        {"name": "check_file_exists", "args": {"filename": "Makefile"}},
        {"name": "check_file_exists", "args": {"filename": "docker-compose.yml"}},
        {"name": "check_build_scripts", "args": {}},
        {"name": "check_error_handling", "args": {}},
        {"name": "check_logging_config", "args": {}},
        {"name": "check_devcontainer", "args": {}},
    ],
    "D5": [
        {"name": "check_file_exists", "args": {"filename": "CLAUDE.md"}},
        {"name": "check_file_exists", "args": {"filename": ".cursorrules"}},
        {"name": "check_adr_records", "args": {}},
        {"name": "check_design_patterns", "args": {}},
        {"name": "check_extensibility", "args": {}},
        {"name": "check_refactoring_safety", "args": {}},
    ],
}


def has_tool_results(messages: list[Message]) -> bool:
    """Check if any tool results are present in the conversation."""
    return any(msg.role == "tool" for msg in messages)


def extract_tool_results(messages: list[Message]) -> dict[str, Any]:
    """Extract tool results from messages into a dict."""
    results = {}
    tool_call_id_to_name = {}

    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_call_id_to_name[tc.get("id", "")] = tc.get("function", {}).get("name", "")

    for msg in messages:
        if msg.role == "tool" and msg.tool_call_id:
            name = tool_call_id_to_name.get(msg.tool_call_id, msg.name or "unknown")
            try:
                results[name] = json.loads(msg.content or "{}")
            except (json.JSONDecodeError, TypeError):
                results[name] = msg.content

    return results


# ─── Score Generation ─────────────────────────────────────────────────────────

def compute_score_from_results(results: dict, items: list[dict]) -> list[dict]:
    """Generate scores based on tool results."""
    scored_items = []
    for item in items:
        base_score = item.get("base_score", 5)
        bonus = 0

        # Heuristic: adjust score based on what files/configs exist
        for indicator in item.get("positive_indicators", []):
            for key, val in results.items():
                if isinstance(val, dict):
                    val_str = json.dumps(val)
                else:
                    val_str = str(val)
                if indicator in val_str and ("true" in val_str.lower() or "exist" in val_str.lower() or "found" in val_str.lower()):
                    bonus += 1
                    break

        for indicator in item.get("negative_indicators", []):
            for key, val in results.items():
                if isinstance(val, dict):
                    val_str = json.dumps(val)
                else:
                    val_str = str(val)
                if indicator in val_str and ("false" in val_str.lower() or "not found" in val_str.lower() or "missing" in val_str.lower()):
                    bonus -= 1
                    break

        score = max(0, min(10, base_score + bonus + random.randint(-1, 1)))
        scored_items.append({
            "id": item["id"],
            "name": item["name"],
            "score": score,
            "max_score": 10,
            "reasoning": generate_reasoning(item["name"], score, results),
        })

    return scored_items


def generate_reasoning(item_name: str, score: int, results: dict) -> str:
    """Generate a brief reasoning string for the score."""
    if score >= 9:
        return f"{item_name}：配置完善，满足卓越标准，所有关键指标均已覆盖。"
    elif score >= 7:
        return f"{item_name}：基本完善，满足优秀标准，个别细节可进一步改进。"
    elif score >= 4:
        return f"{item_name}：部分满足要求，处于良好水平，仍有明显改进空间。"
    elif score >= 1:
        return f"{item_name}：不足，仅满足最低要求，建议优先改进此项。"
    else:
        return f"{item_name}：缺失，未找到相关配置或实现，需要从头建立。"


# ─── Dimension Evaluation Configs ────────────────────────────────────────────

DIMENSION_EVAL_CONFIGS = {
    "D1": {
        "name": "上下文可理解性",
        "weight": 0.20,
        "items": [
            {"id": "1.1", "name": "项目全局描述文档", "base_score": 5, "positive_indicators": ["README.md", "ARCHITECTURE.md"], "negative_indicators": []},
            {"id": "1.2", "name": "目录结构清晰度", "base_score": 5, "positive_indicators": ["semantic", "layers", "structure"], "negative_indicators": ["flat", "cluttered"]},
            {"id": "1.3", "name": "命名规范一致性", "base_score": 5, "positive_indicators": ["eslint", "consistent", "naming"], "negative_indicators": ["inconsistent", "mixed"]},
            {"id": "1.4", "name": "内联文档与注释质量", "base_score": 4, "positive_indicators": ["docstring", "jsdoc", "comments"], "negative_indicators": ["no_comments", "missing"]},
            {"id": "1.5", "name": "依赖关系透明度", "base_score": 5, "positive_indicators": ["lock_file", "lockfile", "dependency"], "negative_indicators": ["circular", "implicit"]},
        ],
    },
    "D2": {
        "name": "规约驱动能力 (SDD)",
        "weight": 0.25,
        "items": [
            {"id": "2.1", "name": "类型系统完备性", "base_score": 4, "positive_indicators": ["typescript", "pydantic", "strict"], "negative_indicators": ["any", "untyped"]},
            {"id": "2.2", "name": "接口契约定义", "base_score": 3, "positive_indicators": ["openapi", "swagger", "graphql", "protobuf"], "negative_indicators": []},
            {"id": "2.3", "name": "数据校验与Schema定义", "base_score": 4, "positive_indicators": ["zod", "joi", "pydantic", "schema"], "negative_indicators": ["no_validation"]},
            {"id": "2.4", "name": "模块接口边界", "base_score": 4, "positive_indicators": ["interface", "abstract", "di"], "negative_indicators": ["coupled", "concrete"]},
            {"id": "2.5", "name": "配置规约与环境管理", "base_score": 5, "positive_indicators": [".env", "env.example", "config"], "negative_indicators": ["hardcoded"]},
        ],
    },
    "D3": {
        "name": "边界控制与安全护栏",
        "weight": 0.20,
        "items": [
            {"id": "3.1", "name": "测试覆盖与验证机制", "base_score": 4, "positive_indicators": ["test", "spec", "coverage"], "negative_indicators": ["no_tests", "missing"]},
            {"id": "3.2", "name": "Lint/格式化强制约束", "base_score": 5, "positive_indicators": ["eslint", "prettier", "ruff", "black"], "negative_indicators": []},
            {"id": "3.3", "name": "变更范围可控性", "base_score": 4, "positive_indicators": ["CODEOWNERS", "monorepo", "workspace"], "negative_indicators": ["coupled"]},
            {"id": "3.4", "name": "版本控制与回滚能力", "base_score": 5, "positive_indicators": ["conventional", "changelog", "commit"], "negative_indicators": ["force_push", "no_branch"]},
            {"id": "3.5", "name": "权限与安全模型", "base_score": 5, "positive_indicators": ["gitignore", "secrets", "vault"], "negative_indicators": ["hardcoded_secret", "exposed"]},
        ],
    },
    "D4": {
        "name": "任务可执行性",
        "weight": 0.20,
        "items": [
            {"id": "4.1", "name": "构建与运行便捷性", "base_score": 5, "positive_indicators": ["Makefile", "docker-compose", "devcontainer"], "negative_indicators": []},
            {"id": "4.2", "name": "错误反馈质量", "base_score": 4, "positive_indicators": ["error_type", "structured", "trace"], "negative_indicators": ["generic_error", "silent"]},
            {"id": "4.3", "name": "脚本与自动化工具", "base_score": 5, "positive_indicators": ["scripts", "make", "taskfile"], "negative_indicators": ["manual", "missing"]},
            {"id": "4.4", "name": "可调试与可观测性", "base_score": 4, "positive_indicators": ["launch.json", "logging", "opentelemetry"], "negative_indicators": ["console_log_only"]},
            {"id": "4.5", "name": "增量构建与热重载", "base_score": 4, "positive_indicators": ["hmr", "watch", "vite", "webpack"], "negative_indicators": ["full_rebuild"]},
        ],
    },
    "D5": {
        "name": "演进友好性",
        "weight": 0.15,
        "items": [
            {"id": "5.1", "name": "设计模式一致性", "base_score": 4, "positive_indicators": ["adr", "pattern", "consistent"], "negative_indicators": ["mixed_patterns"]},
            {"id": "5.2", "name": "可扩展性设计", "base_score": 4, "positive_indicators": ["plugin", "middleware", "hook"], "negative_indicators": ["rigid", "switch_case"]},
            {"id": "5.3", "name": "知识库与决策记录", "base_score": 3, "positive_indicators": ["CLAUDE.md", "CONTRIBUTING.md", "adr", "docs"], "negative_indicators": []},
            {"id": "5.4", "name": "重构安全网", "base_score": 4, "positive_indicators": ["type", "test", "ci"], "negative_indicators": ["no_safety"]},
            {"id": "5.5", "name": "Agent专属指引文件", "base_score": 2, "positive_indicators": ["CLAUDE.md", ".cursorrules", "copilot-instructions"], "negative_indicators": []},
        ],
    },
}


# ─── Response Builders ────────────────────────────────────────────────────────

def build_tool_calls_response(dim: str, tools: list[dict] | None) -> dict:
    """Build a response that requests tool calls for the given dimension."""
    available_tool_names = set()
    if tools:
        for t in tools:
            fn = t.get("function", {})
            available_tool_names.add(fn.get("name", ""))

    tool_calls_config = DIMENSION_TOOL_CALLS.get(dim, DIMENSION_TOOL_CALLS["D1"])
    tool_calls = []

    for tc in tool_calls_config:
        if not available_tool_names or tc["name"] in available_tool_names:
            call_id = f"call_{uuid.uuid4().hex[:8]}"
            tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc["args"]),
                },
            })

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "mock-gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600},
    }


def build_evaluation_response(dim: str, tool_results: dict) -> dict:
    """Build a dimension evaluation response based on tool results."""
    config = DIMENSION_EVAL_CONFIGS.get(dim, DIMENSION_EVAL_CONFIGS["D1"])
    scored_items = compute_score_from_results(tool_results, config["items"])

    total = sum(item["score"] for item in scored_items)
    percentage = (total / 50) * 100

    evaluation = {
        "dimension": dim,
        "name": config["name"],
        "weight": config["weight"],
        "items": scored_items,
        "total": total,
        "max_total": 50,
        "percentage": round(percentage, 1),
        "weighted_score": round(percentage * config["weight"], 2),
    }

    # Format as readable text with embedded JSON
    summary_lines = [
        f"## {dim} — {config['name']} 评估完成\n",
        f"**总分**: {total}/50 ({percentage:.1f}%)\n",
        "",
        "### 子项评分：",
    ]
    for item in scored_items:
        summary_lines.append(f"- **{item['id']} {item['name']}**: {item['score']}/10 — {item['reasoning']}")

    summary_lines += [
        "",
        "### 结构化评估结果：",
        "```json",
        json.dumps(evaluation, ensure_ascii=False, indent=2),
        "```",
        "",
        "EVALUATION_COMPLETE",
    ]

    content = "\n".join(summary_lines)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "mock-gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 800, "completion_tokens": 400, "total_tokens": 1200},
    }


def build_summary_response(messages: list[Message]) -> dict:
    """Build the final summary report from all dimension results."""
    import re

    all_dim_results = {}
    for msg in messages:
        if msg.role == "user" and msg.content:
            # Strategy 1: extract JSON from markdown ```json ... ``` block
            match = re.search(r"```json\s*(.+?)```", msg.content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1).strip())
                    if isinstance(data, dict):
                        # data is a dict of {dim_id: {dimension: ..., ...}}
                        for key, val in data.items():
                            if isinstance(val, dict) and "dimension" in val:
                                all_dim_results[val["dimension"]] = val
                except (json.JSONDecodeError, TypeError):
                    pass

            # Strategy 2: direct JSON parse (for plain JSON messages)
            if not all_dim_results:
                try:
                    data = json.loads(msg.content)
                    if isinstance(data, dict):
                        if "dimension" in data:
                            all_dim_results[data["dimension"]] = data
                        else:
                            for key, val in data.items():
                                if isinstance(val, dict) and "dimension" in val:
                                    all_dim_results[val["dimension"]] = val
                except (json.JSONDecodeError, TypeError):
                    pass

    if not all_dim_results:
        content = "汇总报告：维度数据不足，请确保所有维度评估已完成。"
    else:
        total_weighted = sum(
            v.get("weighted_score", 0) for v in all_dim_results.values()
        )
        grade = compute_grade(total_weighted)
        content = build_summary_content(all_dim_results, total_weighted, grade)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "mock-gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 600, "total_tokens": 1800},
    }


def compute_grade(total_score: float) -> str:
    if total_score >= 90:
        return "S"
    elif total_score >= 75:
        return "A"
    elif total_score >= 60:
        return "B"
    elif total_score >= 40:
        return "C"
    elif total_score >= 20:
        return "D"
    else:
        return "F"


GRADE_DESCRIPTIONS = {
    "S": "卓越 — Agent 可近乎自主完成大部分任务，人工仅需最终审核",
    "A": "优秀 — Agent 高效协作，仅在复杂决策时需少量人工确认",
    "B": "良好 — Agent 可有效辅助，中等频率需人工介入修正方向",
    "C": "及格 — Agent 勉强可用，高频需人工纠偏，建议优先改进",
    "D": "较差 — Agent 难以有效工作，需先进行仓库基础设施建设",
    "F": "极差 — Agent 基本无法使用，需从项目结构层面根本性改造",
}


def build_summary_content(results: dict, total: float, grade: str) -> str:
    lines = [
        "# Agentic Coding 友好度评估报告",
        "",
        "## 综合评分汇总",
        "",
        f"| 编号 | 评估维度 | 权重 | 原始得分(/50) | 百分制 | 加权得分 |",
        f"|:----:|---------|:----:|:------------:|:------:|:-------:|",
    ]

    dim_order = ["D1", "D2", "D3", "D4", "D5"]
    dim_names = {
        "D1": "🧠 上下文可理解性",
        "D2": "📐 规约驱动能力 (SDD)",
        "D3": "🛡️ 边界控制与安全护栏",
        "D4": "⚡ 任务可执行性",
        "D5": "🌱 演进友好性",
    }

    for dim in dim_order:
        if dim in results:
            r = results[dim]
            lines.append(
                f"| {dim} | {dim_names.get(dim, dim)} | {int(r.get('weight', 0)*100)}% "
                f"| {r.get('total', 0)}/50 | {r.get('percentage', 0):.1f}% | {r.get('weighted_score', 0):.1f} |"
            )

    lines += [
        f"| | **合计** | **100%** | | | **{total:.1f}** |",
        "",
        "## 最终评级",
        "",
        f"- **综合加权总分**: {total:.1f} 分",
        f"- **最终评级**: **{grade}** — {GRADE_DESCRIPTIONS.get(grade, '')}",
        "",
        "## 各维度详情",
        "",
    ]

    for dim in dim_order:
        if dim in results:
            r = results[dim]
            lines.append(f"### {dim} — {r.get('name', dim)}")
            for item in r.get("items", []):
                lines.append(
                    f"- **{item['id']} {item['name']}**: {item['score']}/10 — {item.get('reasoning', '')}"
                )
            lines.append("")

    lines.append("---")
    lines.append("*本报告由 Agentic Evaluator 多智能体系统生成*")

    return "\n".join(lines)


# ─── FastAPI Endpoint ─────────────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    req = ChatCompletionRequest(**body)

    dim = detect_dimension(req.messages)

    # Summary agent detection
    is_summary = any(
        kw in (msg.content or "")
        for msg in req.messages
        for kw in DIMENSION_KEYWORDS["SUMMARY"]
    )

    if is_summary:
        return JSONResponse(build_summary_response(req.messages))

    if has_tool_results(req.messages):
        tool_results = extract_tool_results(req.messages)
        return JSONResponse(build_evaluation_response(dim, tool_results))
    else:
        return JSONResponse(build_tool_calls_response(dim, req.tools))


@app.get("/health")
async def health():
    return {"status": "ok", "server": "mock-llm"}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": "mock-gpt-4", "object": "model", "created": int(time.time()), "owned_by": "mock"}],
    }


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    uvicorn.run("mock_server.server:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
