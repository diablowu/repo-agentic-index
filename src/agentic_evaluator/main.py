"""
CLI entry point for the Agentic Evaluator tool.

Usage:
    # Start mock LLM server (in one terminal):
    uv run mock-server

    # Run evaluation (in another terminal):
    uv run evaluate /path/to/repo

    # With real OpenAI-compatible API:
    LLM_BASE_URL=https://api.openai.com/v1 LLM_API_KEY=sk-... uv run evaluate /path/to/repo

    # Save JSON report:
    uv run evaluate /path/to/repo --output report.json
"""

import sys
from pathlib import Path

import typer
from rich.console import Console

from .agents.orchestrator import EvaluationOrchestrator

console = Console()
app = typer.Typer(
    name="agentic-evaluator",
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

    # Suppress AutoGen verbose output unless --verbose
    if not verbose:
        import logging

        logging.getLogger("autogen").setLevel(logging.WARNING)

    # Run evaluation
    try:
        orchestrator = EvaluationOrchestrator()
        report = orchestrator.evaluate(str(repo))
        orchestrator.print_report(report)

        if output:
            orchestrator.save_report(report, output)

    except KeyboardInterrupt:
        console.print("\n[yellow]评估被用户中断[/yellow]")
        raise typer.Exit(code=130) from None
    except Exception as e:
        console.print(f"\n[red]评估失败: {e}[/red]")
        if verbose:
            raise
        raise typer.Exit(code=1) from e


@app.command()
def start_mock_server(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Server host"),
    port: int = typer.Option(8000, "--port", "-p", help="Server port"),
) -> None:
    """Start the mock OpenAI-compatible LLM server for testing."""
    import uvicorn

    from mock_server.server import app as mock_app

    console.print(f"[green]Starting mock LLM server at http://{host}:{port}[/green]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    uvicorn.run(mock_app, host=host, port=port)


@app.command()
def check_server(
    url: str = typer.Option(
        "http://localhost:8000",
        "--url",
        help="Mock server URL to check",
    ),
) -> None:
    """Check if the mock LLM server is running."""
    import httpx

    try:
        resp = httpx.get(f"{url}/health", timeout=5.0)
        if resp.status_code == 200:
            console.print(f"[green]✓ Mock server is running at {url}[/green]")
        else:
            console.print(f"[yellow]Server responded with status {resp.status_code}[/yellow]")
    except Exception as e:
        console.print(f"[red]✗ Could not connect to {url}: {e}[/red]")
        console.print("[dim]Start the server with: uv run mock-server[/dim]")
        raise typer.Exit(code=1) from None


def main():
    """Entry point: if first arg looks like a path, run evaluate directly."""
    args = sys.argv[1:]
    # If first argument is a path (not a subcommand name), insert 'evaluate' subcommand
    known_commands = {"evaluate", "start-mock-server", "check-server", "--help", "-h"}
    if args and args[0] not in known_commands and not args[0].startswith("-"):
        sys.argv.insert(1, "evaluate")
    app()


if __name__ == "__main__":
    main()
