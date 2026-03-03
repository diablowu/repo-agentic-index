"""
CLI entry point for the Agentic Evaluator tool.

Usage:
    # With real OpenAI-compatible API:
    LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-... repo-agent-friendly-evaluate /path/to/repo

    # Save JSON report:
    repo-agent-friendly-evaluate /path/to/repo --output report.json
"""

import sys
from pathlib import Path

import typer
from rich.console import Console

from .agents.orchestrator import EvaluationOrchestrator

console = Console()
app = typer.Typer(
    name="repo-agent-friendly-evaluate",
    help="Multi-agent Agentic Coding Friendliness Evaluator (Framework v1.0)",
    add_completion=False,
)


@app.command()
def evaluate(
    repo_path: str = typer.Argument(
        ...,
        help="Path to the repository to evaluate",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Save JSON report to this file path",
    ),
    llm_url: str | None = typer.Option(
        None,
        "--llm-url",
        help="OpenAI-compatible API base URL (overrides LLM_BASE_URL env var)",
        envvar="LLM_BASE_URL",
    ),
    llm_key: str | None = typer.Option(
        None,
        "--llm-key",
        help="API key for the LLM endpoint",
        envvar="LLM_API_KEY",
    ),
    model: str = typer.Option(
        "mock-gpt-4",
        "--model",
        help="Model name to use",
        envvar="LLM_MODEL",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed AutoGen conversation logs",
    ),
    only_evaluate: bool = typer.Option(
        False,
        "--only-evaluate",
        help="Skip summary analysis, output scores only",
    ),
    output_format: str = typer.Option(
        "json",
        "--output-format",
        help="Output file format when --output is set: json or md",
        show_choices=True,
    ),
) -> None:
    """Evaluate a repository's Agentic Coding friendliness (D1-D5)."""

    # Validate path
    repo = Path(repo_path).resolve()
    if not repo.exists():
        console.print(f"[red]Error: Repository path not found: {repo}[/red]")
        raise typer.Exit(code=1)

    # Override config from CLI options
    if llm_url:
        import os

        os.environ["LLM_BASE_URL"] = llm_url
    if llm_key:
        import os

        os.environ["LLM_API_KEY"] = llm_key
    if model:
        import os

        os.environ["LLM_MODEL"] = model

    # Always suppress AutoGen internal logging (we use our own verbose output)
    import logging

    logging.getLogger("autogen").setLevel(logging.WARNING)
    logging.getLogger("autogen_agentchat").setLevel(logging.WARNING)
    logging.getLogger("autogen_core").setLevel(logging.WARNING)
    logging.getLogger("autogen_ext").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Validate output_format
    if output_format not in ("json", "md"):
        console.print("[red]Error: --output-format must be 'json' or 'md'[/red]")
        raise typer.Exit(code=1)

    # Run evaluation
    try:
        orchestrator = EvaluationOrchestrator()
        report = orchestrator.evaluate(str(repo), only_evaluate=only_evaluate, verbose=verbose)
        orchestrator.print_report(report, only_evaluate=only_evaluate)

        if output:
            orchestrator.save_report(report, output, output_format=output_format)

    except KeyboardInterrupt:
        console.print("\n[yellow]评估被用户中断[/yellow]")
        raise typer.Exit(code=130) from None
    except Exception as e:
        console.print(f"\n[red]评估失败: {e}[/red]")
        if verbose:
            raise
        raise typer.Exit(code=1) from e


def main():
    """Entry point."""
    args = sys.argv[1:]
    # If first argument looks like a path (not a flag), treat it as the repo_path directly
    if args and not args[0].startswith("-"):
        sys.argv.insert(1, "evaluate")
    app()


if __name__ == "__main__":
    main()
