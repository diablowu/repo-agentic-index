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


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from LLM output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
from dataclasses import dataclass, field
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import box

from ..config import get_model_client
from ..skills.file_scanner import set_repo_path
from .dimension_agents import (
    D1ContextAgent,
    D2SDDAgent,
    D3BoundaryAgent,
    D4ExecutabilityAgent,
    D5EvolutionAgent,
)

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

    def summarize(self, dimension_results: dict[str, DimensionResult]) -> str:
        """Generate the final summary report from dimension results."""
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

    def evaluate(self, repo_path: str) -> EvaluationReport:
        """Run the full evaluation for a repository."""
        repo = Path(repo_path).resolve()
        if not repo.exists():
            raise FileNotFoundError(f"Repository path not found: {repo}")

        # Set global repo path for all skill functions
        set_repo_path(str(repo))

        report = EvaluationReport(repo_path=str(repo))

        console.print(Panel(
            f"[bold cyan]Agentic Coding 友好度评估[/bold cyan]\n"
            f"仓库路径: [green]{repo}[/green]",
            title="评估开始",
            border_style="blue",
        ))

        dim_configs = {
            "D1": ("上下文可理解性", 0.30),
            "D2": ("规约驱动能力 (SDD)", 0.30),
            "D3": ("边界控制与安全护栏", 0.15),
            "D4": ("任务可执行性", 0.15),
            "D5": ("演进友好性", 0.10),
        }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for dim_id, (dim_name, weight) in dim_configs.items():
                task = progress.add_task(
                    f"[yellow]评估 {dim_id} — {dim_name}...[/yellow]",
                    total=None,
                )

                agent = self.agents[dim_id]
                raw_result = agent.evaluate(str(repo))

                if raw_result:
                    actual_weight = raw_result.get("weight", weight)
                    total_score = raw_result.get("total", 0)
                    max_total = raw_result.get("max_total", 50)
                    percentage = (total_score / max_total * 100) if max_total > 0 else 0.0
                    weighted_score = percentage * actual_weight
                    dim_result = DimensionResult(
                        dimension=dim_id,
                        name=raw_result.get("name", dim_name),
                        weight=actual_weight,
                        items=raw_result.get("items", []),
                        total=total_score,
                        max_total=max_total,
                        percentage=percentage,
                        weighted_score=weighted_score,
                        raw=raw_result,
                    )
                else:
                    # Fallback if extraction failed
                    console.print(f"[yellow]警告: {dim_id} 评估结果提取失败，使用默认值[/yellow]")
                    dim_result = DimensionResult(
                        dimension=dim_id,
                        name=dim_name,
                        weight=weight,
                        total=0,
                        percentage=0.0,
                        weighted_score=0.0,
                    )

                report.dimensions[dim_id] = dim_result
                progress.update(task, completed=True, description=f"[green]✓ {dim_id} — {dim_name} 完成[/green]")

        # Compute totals
        report.total_weighted_score = sum(r.weighted_score for r in report.dimensions.values())
        report.grade, _ = compute_grade(report.total_weighted_score)

        # Run summary agent
        console.print("\n[bold]生成综合报告...[/bold]")
        report.summary_text = self.summary_agent.summarize(report.dimensions)

        return report

    def print_report(self, report: EvaluationReport) -> None:
        """Print a formatted evaluation report to the console."""
        grade, grade_label = compute_grade(report.total_weighted_score)

        grade_colors = {
            "S": "bold magenta", "A": "bold green", "B": "green",
            "C": "yellow", "D": "red", "F": "bold red",
        }
        color = grade_colors.get(grade, "white")

        console.print()
        console.print(Panel(
            f"[{color}]评级: {grade} — {grade_label}[/{color}]\n"
            f"综合加权总分: [bold]{report.total_weighted_score:.1f}[/bold] / 100",
            title="🏆 最终评估结果",
            border_style="green" if report.total_weighted_score >= 60 else "red",
        ))

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
                color_cell = (
                    "green" if pct >= 75 else
                    "yellow" if pct >= 50 else
                    "red"
                )
                table.add_row(
                    dim_id,
                    r.name,
                    f"{int(r.weight * 100)}%",
                    f"{r.total}/50",
                    f"[{color_cell}]{pct:.1f}%[/{color_cell}]",
                    f"{r.weighted_score:.1f}",
                )

        table.add_row(
            "", "[bold]合计[/bold]", "[bold]100%[/bold]",
            "", "",
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
                    "green" if score >= 8 else
                    "blue" if score >= 6 else
                    "yellow" if score >= 4 else
                    "red"
                )
                sub_table.add_row(
                    item.get("id", ""),
                    item.get("name", ""),
                    f"[{score_color}]{score}/10[/{score_color}]",
                    item.get("reasoning", "")[:60] + "..." if len(item.get("reasoning", "")) > 60 else item.get("reasoning", ""),
                )

            console.print(sub_table)

        # Summary text
        if report.summary_text:
            console.print(Panel(
                report.summary_text,
                title="📝 综合分析与改进建议",
                border_style="blue",
            ))

    def save_report(self, report: EvaluationReport, output_path: str) -> None:
        """Save the evaluation report as JSON."""
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
        }

        Path(output_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        console.print(f"\n[green]报告已保存至: {output_path}[/green]")
