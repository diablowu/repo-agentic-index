"""
Orchestrator: coordinates dimension agents and the summary agent.

Flow:
  1. Set global repo path for all skill functions
  2. Run D1–D5 agents sequentially (each calls tools + LLM evaluation)
  3. Pass all results to the SummaryAgent
  4. Return the final EvaluationReport
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ..config import get_model_client
from ..skills.file_scanner import set_repo_path
from .dimension_agents import (
    D1ContextAgent,
    D2SDDAgent,
    D3BoundaryAgent,
    D4ExecutabilityAgent,
    D5EvolutionAgent,
)


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from LLM output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


console = Console()


# ─── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class DimensionResult:
    dimension: str
    name: str
    weight: float
    items: list[dict] = field(default_factory=list)
    total: int = 0
    max_total: int = 50
    percentage: float = 0.0
    weighted_score: float = 0.0
    raw: dict | None = None


@dataclass
class EvaluationReport:
    repo_path: str
    dimensions: dict[str, DimensionResult] = field(default_factory=dict)
    total_weighted_score: float = 0.0
    grade: str = "F"
    summary_text: str = ""
    improvements: dict[str, dict] = field(default_factory=dict)


GRADE_MAP = {
    (90, 101): ("S", "卓越"),
    (75, 90): ("A", "优秀"),
    (60, 75): ("B", "良好"),
    (40, 60): ("C", "及格"),
    (20, 40): ("D", "较差"),
    (0, 20): ("F", "极差"),
}


def compute_grade(score: float) -> tuple[str, str]:
    for (low, high), (grade, label) in GRADE_MAP.items():
        if low <= score < high:
            return grade, label
    return "F", "极差"


# ─── Summary Agent ────────────────────────────────────────────────────────────

SUMMARY_SYSTEM_PROMPT = """你是一位专业的代码仓库综合评估专家，负责汇总各维度的评估结果并生成最终报告。

你将收到 D1–D5 五个维度的详细评分数据，请：
1. 计算加权总分（各维度已含权重）
2. 给出最终评级（S/A/B/C/D/F）
3. 识别最薄弱的3个改进点
4. 给出改进优先级建议

请直接输出报告，不需要调用额外工具。报告使用中文，格式清晰易读。
"""


class SummaryAgent:
    """Aggregates dimension results and generates the final report."""

    def __init__(self):
        self.assistant = AssistantAgent(
            name="SummaryAgent",
            model_client=get_model_client(),
            system_message=SUMMARY_SYSTEM_PROMPT,
        )

    def summarize(
        self, dimension_results: dict[str, DimensionResult], verbose: bool = False
    ) -> str:
        """Generate the final summary report from dimension results."""
        from autogen_agentchat.base import TaskResult as TR

        from .dimension_agents import _TAG_COLORS, _print_verbose_event, _verbose_console

        data = {}
        for dim_id, result in dimension_results.items():
            data[dim_id] = {
                "dimension": result.dimension,
                "name": result.name,
                "weight": result.weight,
                "total": result.total,
                "percentage": result.percentage,
                "weighted_score": result.weighted_score,
                "items": result.items,
            }

        total = sum(r.weighted_score for r in dimension_results.values())
        grade, grade_label = compute_grade(total)

        message = (
            f"以下是各维度的评估结果，请生成综合报告。\n\n"
            f"**加权总分**: {total:.1f}/100\n"
            f"**评级**: {grade} — {grade_label}\n\n"
            f"**各维度数据**:\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n\n"
            "请分析薄弱点并给出改进建议。"
        )

        async def _run_summary():
            team = RoundRobinGroupChat(
                participants=[self.assistant],
                termination_condition=MaxMessageTermination(3),
            )
            if verbose:
                color = _TAG_COLORS.get("SummaryAgent", "white")
                _verbose_console.rule(f"[{color}][SummaryAgent] 开始生成综合报告[/{color}]")
                final_result = None
                async for event in team.run_stream(task=message):
                    if isinstance(event, TR):
                        final_result = event
                    else:
                        _print_verbose_event("SummaryAgent", event)
                _verbose_console.rule(f"[{color}][SummaryAgent] 综合报告完成[/{color}]")
                if final_result:
                    for msg in reversed(final_result.messages):
                        content = getattr(msg, "content", None)
                        if content and isinstance(content, str):
                            return _strip_think_tags(content)
            else:
                result = await team.run(task=message)
                for msg in reversed(result.messages):
                    content = getattr(msg, "content", None)
                    if content and isinstance(content, str):
                        return _strip_think_tags(content)
            return f"评估完成。总分: {total:.1f}，评级: {grade}"

        try:
            return asyncio.run(_run_summary())
        except RuntimeError:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _run_summary())
                return future.result()


# ─── Improvement Agent ────────────────────────────────────────────────────────

IMPROVEMENT_SYSTEM_PROMPT = """你是一位专业的代码仓库改进建议专家。

你将收到一份代码仓库各维度的评估数据，包括子项得分和评分理由。

## 任务

针对每个维度，分析低分项目（score/max_score < 0.8），识别核心问题，并给出**具体可操作的改进建议**。

## 要求

1. 重点分析得分偏低的子项（score/max_score < 0.8）
2. 每个维度输出 3-5 条改进建议
3. 建议要具体到文件名、命令、代码结构层面（如「创建 CLAUDE.md 文件」而非「改善文档」）
4. 每条建议标注优先级：P0（关键/立即修复）、P1（重要/近期完成）、P2（优化/长期改进）
5. 不需要调用任何工具，直接基于输入数据分析

## 输出格式

仅输出以下结构的 JSON，不要有其他说明文字：

```json
{
  "D1": {
    "issues": ["问题描述1", "问题描述2"],
    "suggestions": [
      {"priority": "P0", "action": "具体操作步骤..."},
      {"priority": "P1", "action": "具体操作步骤..."}
    ]
  },
  "D2": { "issues": [...], "suggestions": [...] },
  "D3": { "issues": [...], "suggestions": [...] },
  "D4": { "issues": [...], "suggestions": [...] },
  "D5": { "issues": [...], "suggestions": [...] }
}
```
"""


def _extract_improvement_json(task_result) -> dict | None:
    """Extract the improvement suggestions JSON from the agent's task result."""
    for msg in reversed(task_result.messages):
        content = getattr(msg, "content", None)
        if not content or not isinstance(content, str):
            continue
        content = _strip_think_tags(content)

        # Strategy 1: Extract from ```json block
        match = re.search(r"```json\s*(.+?)```", content, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
            try:
                data = json.loads(json_str)
                if isinstance(data, dict) and any(k.startswith("D") for k in data):
                    return data
            except json.JSONDecodeError:
                pass

        # Strategy 2: Find top-level JSON object by brace counting
        start = content.find("{")
        if start >= 0:
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
                    if isinstance(data, dict) and any(k.startswith("D") for k in data):
                        return data
                except json.JSONDecodeError:
                    pass

    return None


class ImprovementAgent:
    """Analyzes dimension evaluation results and generates per-dimension improvement suggestions."""

    def analyze(
        self, dimension_results: dict[str, DimensionResult], verbose: bool = False
    ) -> dict[str, dict]:
        """Analyze dimension results and return structured improvement suggestions."""
        from autogen_agentchat.agents import AssistantAgent as _AA
        from autogen_agentchat.base import TaskResult as TR
        from autogen_agentchat.conditions import MaxMessageTermination
        from autogen_agentchat.teams import RoundRobinGroupChat

        from .dimension_agents import _TAG_COLORS, _print_verbose_event, _verbose_console

        data = {}
        for dim_id, dim_result in dimension_results.items():
            data[dim_id] = {
                "name": dim_result.name,
                "percentage": round(dim_result.percentage, 1),
                "items": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "score": item.get("score"),
                        "max_score": item.get("max_score", 10),
                        "reasoning": item.get("reasoning", ""),
                    }
                    for item in dim_result.items
                ],
            }

        task = (
            "以下是代码仓库各维度的评估数据，请分析低分项的问题并给出改进建议。\n\n"
            f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```\n\n"
            "请按照系统提示的 JSON 格式输出改进建议。"
        )

        agent = _AA(
            name="ImprovementAgent",
            model_client=get_model_client(),
            system_message=IMPROVEMENT_SYSTEM_PROMPT,
        )

        color = _TAG_COLORS.get("ImprovementAgent", "white")
        termination = MaxMessageTermination(3)

        async def _run():
            team = RoundRobinGroupChat(
                participants=[agent],
                termination_condition=termination,
            )
            if verbose:
                _verbose_console.rule(f"[{color}][ImprovementAgent] 开始生成改进建议[/{color}]")
                final: TR | None = None
                async for event in team.run_stream(task=task):
                    if isinstance(event, TR):
                        final = event
                    else:
                        _print_verbose_event("ImprovementAgent", event)
                _verbose_console.rule(f"[{color}][ImprovementAgent] 改进建议完成[/{color}]")
                return _extract_improvement_json(final) if final else None
            else:
                result = await team.run(task=task)
                return _extract_improvement_json(result)

        try:
            raw = asyncio.run(_run())
        except RuntimeError:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _run())
                raw = future.result()

        return raw if isinstance(raw, dict) else {}


# ─── Orchestrator ─────────────────────────────────────────────────────────────


class EvaluationOrchestrator:
    """
    Coordinates the full evaluation pipeline:
    - Initializes all dimension agents
    - Runs them sequentially
    - Aggregates results via SummaryAgent
    - Returns EvaluationReport
    """

    def __init__(self):
        self.agents = {
            "D1": D1ContextAgent(),
            "D2": D2SDDAgent(),
            "D3": D3BoundaryAgent(),
            "D4": D4ExecutabilityAgent(),
            "D5": D5EvolutionAgent(),
        }
        self.summary_agent = SummaryAgent()
        self.improvement_agent = ImprovementAgent()

    def evaluate(
        self, repo_path: str, only_evaluate: bool = False, verbose: bool = False
    ) -> EvaluationReport:
        """Run the full evaluation for a repository."""
        repo = Path(repo_path).resolve()
        if not repo.exists():
            raise FileNotFoundError(f"Repository path not found: {repo}")

        # Set global repo path for all skill functions
        set_repo_path(str(repo))

        report = EvaluationReport(repo_path=str(repo))

        console.print(
            Panel(
                f"[bold cyan]Agentic Coding 友好度评估[/bold cyan]\n"
                f"仓库路径: [green]{repo}[/green]",
                title="评估开始",
                border_style="blue",
            )
        )

        dim_configs = {
            "D1": ("上下文可理解性", 0.30),
            "D2": ("规约驱动能力 (SDD)", 0.30),
            "D3": ("边界控制与安全护栏", 0.15),
            "D4": ("任务可执行性", 0.15),
            "D5": ("演进友好性", 0.10),
        }

        def _run_dim(dim_id: str, dim_name: str, weight: float) -> DimensionResult:
            agent = self.agents[dim_id]
            raw_result = agent.evaluate(str(repo), verbose=verbose)
            if raw_result:
                actual_weight = raw_result.get("weight", weight)
                total_score = raw_result.get("total", 0)
                max_total = raw_result.get("max_total", 50)
                percentage = (total_score / max_total * 100) if max_total > 0 else 0.0
                return DimensionResult(
                    dimension=dim_id,
                    name=raw_result.get("name", dim_name),
                    weight=actual_weight,
                    items=raw_result.get("items", []),
                    total=total_score,
                    max_total=max_total,
                    percentage=percentage,
                    weighted_score=percentage * actual_weight,
                    raw=raw_result,
                )
            console.print(f"[yellow]警告: {dim_id} 评估结果提取失败，使用默认值[/yellow]")
            return DimensionResult(
                dimension=dim_id,
                name=dim_name,
                weight=weight,
                total=0,
                percentage=0.0,
                weighted_score=0.0,
            )

        if verbose:
            # Verbose: print directly without Progress spinner
            for dim_id, (dim_name, weight) in dim_configs.items():
                report.dimensions[dim_id] = _run_dim(dim_id, dim_name, weight)
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                for dim_id, (dim_name, weight) in dim_configs.items():
                    ptask = progress.add_task(
                        f"[yellow]评估 {dim_id} — {dim_name}...[/yellow]",
                        total=None,
                    )
                    report.dimensions[dim_id] = _run_dim(dim_id, dim_name, weight)
                    progress.update(
                        ptask,
                        completed=True,
                        description=f"[green]✓ {dim_id} — {dim_name} 完成[/green]",
                    )

        # Compute totals
        report.total_weighted_score = sum(r.weighted_score for r in report.dimensions.values())
        report.grade, _ = compute_grade(report.total_weighted_score)

        # Run summary + improvement agents (skip when only_evaluate=True)
        if not only_evaluate:
            if not verbose:
                console.print("\n[bold]生成综合报告...[/bold]")
            report.summary_text = self.summary_agent.summarize(report.dimensions, verbose=verbose)

            if not verbose:
                console.print("\n[bold]生成改进建议...[/bold]")
            report.improvements = self.improvement_agent.analyze(report.dimensions, verbose=verbose)

        return report

    def print_report(self, report: EvaluationReport, only_evaluate: bool = False) -> None:
        """Print a formatted evaluation report to the console."""
        grade, grade_label = compute_grade(report.total_weighted_score)

        grade_colors = {
            "S": "bold magenta",
            "A": "bold green",
            "B": "green",
            "C": "yellow",
            "D": "red",
            "F": "bold red",
        }
        color = grade_colors.get(grade, "white")

        console.print()
        console.print(
            Panel(
                f"[{color}]评级: {grade} — {grade_label}[/{color}]\n"
                f"综合加权总分: [bold]{report.total_weighted_score:.1f}[/bold] / 100",
                title="🏆 最终评估结果",
                border_style="green" if report.total_weighted_score >= 60 else "red",
            )
        )

        # Dimension scores table
        table = Table(title="📊 各维度评分", box=box.ROUNDED)
        table.add_column("维度", style="cyan", no_wrap=True)
        table.add_column("名称", style="white")
        table.add_column("权重", justify="right")
        table.add_column("原始分(/50)", justify="right")
        table.add_column("百分制", justify="right")
        table.add_column("加权得分", justify="right", style="bold")

        for dim_id in ["D1", "D2", "D3", "D4", "D5"]:
            if dim_id in report.dimensions:
                r = report.dimensions[dim_id]
                pct = r.percentage
                color_cell = "green" if pct >= 75 else "yellow" if pct >= 50 else "red"
                table.add_row(
                    dim_id,
                    r.name,
                    f"{int(r.weight * 100)}%",
                    f"{r.total}/50",
                    f"[{color_cell}]{pct:.1f}%[/{color_cell}]",
                    f"{r.weighted_score:.1f}",
                )

        table.add_row(
            "",
            "[bold]合计[/bold]",
            "[bold]100%[/bold]",
            "",
            "",
            f"[bold]{report.total_weighted_score:.1f}[/bold]",
        )
        console.print(table)

        # Sub-item details per dimension
        for dim_id in ["D1", "D2", "D3", "D4", "D5"]:
            if dim_id not in report.dimensions:
                continue
            r = report.dimensions[dim_id]
            if not r.items:
                continue

            sub_table = Table(title=f"{dim_id} — {r.name} 子项详情", box=box.SIMPLE)
            sub_table.add_column("编号", style="dim")
            sub_table.add_column("子项", style="white")
            sub_table.add_column("得分", justify="right")
            sub_table.add_column("说明", style="dim")

            for item in r.items:
                score = item.get("score", 0)
                score_color = (
                    "green"
                    if score >= 8
                    else "blue"
                    if score >= 6
                    else "yellow"
                    if score >= 4
                    else "red"
                )
                sub_table.add_row(
                    item.get("id", ""),
                    item.get("name", ""),
                    f"[{score_color}]{score}/10[/{score_color}]",
                    item.get("reasoning", "")[:60] + "..."
                    if len(item.get("reasoning", "")) > 60
                    else item.get("reasoning", ""),
                )

            console.print(sub_table)

        # Summary text (skipped when only_evaluate=True)
        if not only_evaluate and report.summary_text:
            console.print(
                Panel(
                    report.summary_text,
                    title="📝 综合分析与改进建议",
                    border_style="blue",
                )
            )

        # Per-dimension improvement suggestions (skipped when only_evaluate=True)
        if not only_evaluate and report.improvements:
            priority_colors = {"P0": "bold red", "P1": "yellow", "P2": "blue"}
            imp_table = Table(title="🔧 逐维度改进建议", box=box.ROUNDED, show_header=True)
            imp_table.add_column("维度", style="cyan", no_wrap=True, width=6)
            imp_table.add_column("优先级", no_wrap=True, width=5)
            imp_table.add_column("改进建议", style="white")

            for dim_id in ["D1", "D2", "D3", "D4", "D5"]:
                if dim_id not in report.improvements:
                    continue
                imp = report.improvements[dim_id]
                first = True
                for sug in imp.get("suggestions", []):
                    p = sug.get("priority", "P2")
                    c = priority_colors.get(p, "white")
                    imp_table.add_row(
                        dim_id if first else "",
                        f"[{c}]{p}[/{c}]",
                        sug.get("action", ""),
                    )
                    first = False

            console.print(imp_table)

    def save_report(
        self, report: EvaluationReport, output_path: str, output_format: str = "json"
    ) -> None:
        """Save the evaluation report as JSON or Markdown."""
        if output_format == "md":
            content = self._build_markdown_report(report)
        else:
            data = {
                "repo_path": report.repo_path,
                "total_weighted_score": report.total_weighted_score,
                "grade": report.grade,
                "dimensions": {
                    dim_id: {
                        "dimension": r.dimension,
                        "name": r.name,
                        "weight": r.weight,
                        "total": r.total,
                        "max_total": r.max_total,
                        "percentage": r.percentage,
                        "weighted_score": r.weighted_score,
                        "items": r.items,
                    }
                    for dim_id, r in report.dimensions.items()
                },
                "summary": report.summary_text,
                "improvements": report.improvements,
            }
            content = json.dumps(data, ensure_ascii=False, indent=2)

        Path(output_path).write_text(content, encoding="utf-8")
        console.print(f"\n[green]报告已保存至: {output_path}[/green]")

    def _build_markdown_report(self, report: EvaluationReport) -> str:
        """Build a Markdown-formatted evaluation report."""
        _, grade_label = compute_grade(report.total_weighted_score)
        lines = [
            "# Agentic Coding 友好度评估报告",
            "",
            f"**仓库**: `{report.repo_path}`  ",
            f"**总分**: {report.total_weighted_score:.1f} / 100  ",
            f"**评级**: {report.grade} — {grade_label}",
            "",
            "---",
            "",
            "## 各维度评分",
            "",
            "| 维度 | 名称 | 权重 | 原始分(/50) | 百分制 | 加权得分 |",
            "|------|------|-----:|------------:|-------:|---------:|",
        ]
        for dim_id in ["D1", "D2", "D3", "D4", "D5"]:
            if dim_id in report.dimensions:
                r = report.dimensions[dim_id]
                lines.append(
                    f"| {dim_id} | {r.name} | {int(r.weight * 100)}% "
                    f"| {r.total}/50 | {r.percentage:.1f}% | {r.weighted_score:.1f} |"
                )
        lines += [
            f"| | **合计** | **100%** | | | **{report.total_weighted_score:.1f}** |",
            "",
        ]

        for dim_id in ["D1", "D2", "D3", "D4", "D5"]:
            if dim_id not in report.dimensions:
                continue
            r = report.dimensions[dim_id]
            if not r.items:
                continue
            lines += [
                f"## {dim_id} — {r.name} 子项详情",
                "",
                "| 编号 | 子项 | 得分 | 说明 |",
                "|------|------|-----:|------|",
            ]
            for item in r.items:
                reasoning = item.get("reasoning", "").replace("|", "｜")
                lines.append(
                    f"| {item.get('id', '')} | {item.get('name', '')} "
                    f"| {item.get('score', 0)}/10 | {reasoning} |"
                )
            lines.append("")

        if report.summary_text:
            lines += [
                "---",
                "",
                "## 综合分析与改进建议",
                "",
                report.summary_text,
            ]

        if report.improvements:
            lines += [
                "",
                "---",
                "",
                "## 逐维度改进建议",
                "",
            ]
            for dim_id in ["D1", "D2", "D3", "D4", "D5"]:
                if dim_id not in report.improvements:
                    continue
                imp = report.improvements[dim_id]
                dim_name = report.dimensions.get(dim_id)
                name = dim_name.name if dim_name else dim_id
                lines += [f"### {dim_id} — {name}", ""]
                for sug in imp.get("suggestions", []):
                    p = sug.get("priority", "P2")
                    action = sug.get("action", "")
                    lines.append(f"- [{p}] {action}")
                lines.append("")

        return "\n".join(lines)
