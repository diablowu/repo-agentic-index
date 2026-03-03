.PHONY: help install test lint format mock evaluate

help: ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## 安装依赖
	uv sync

install-dev: ## 安装开发依赖（含 pre-commit）
	uv sync --dev
	uv run pre-commit install

test: ## 运行测试
	uv run pytest

test-v: ## 运行测试（详细输出）
	uv run pytest -v

lint: ## 运行 Ruff 检查
	uv run ruff check src/ mock_server/ tests/

format: ## 自动格式化代码
	uv run ruff format src/ mock_server/ tests/
	uv run ruff check --fix src/ mock_server/ tests/

mock: ## 启动 Mock LLM 服务器
	uv run mock-server

evaluate: ## 评估当前目录（用法: make evaluate REPO=/path/to/repo）
	uv run evaluate $(REPO)
