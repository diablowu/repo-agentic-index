# Agentic Evaluator

基于 AutoGen 多智能体框架的代码仓库「**Agentic Coding 友好度**」自动评估工具。

根据 [Repository Agentic-Readiness Scoring Framework v1.0](./Agentic-Coding-Evaluation-Framework-v1.0.md)，从 D1–D5 五个维度对目标仓库进行 AI 驱动的量化评分，最终输出 0–100 分的综合报告。

## 评估维度

| 维度 | 名称 | 权重 |
|------|------|------|
| D1 | 上下文可理解性 | 30% |
| D2 | 规约驱动能力（SDD） | 30% |
| D3 | 边界控制与安全护栏 | 15% |
| D4 | 任务可执行性 | 15% |
| D5 | 演进友好性 | 10% |

评级：**S**（≥90）/ **A**（≥75）/ **B**（≥60）/ **C**（≥40）/ **D**（≥20）/ **F**（<20）

## 支持语言

TypeScript · JavaScript · Python · **Go** · **Java** · **Vue** · **SQL/ORM**

---

## Getting Started

### 前置要求

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) 包管理器

```bash
# 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 1. 克隆并安装依赖

```bash
git clone <repo-url>
cd repo-agentic-index
uv sync
```

### 2. 快速体验（使用 Mock LLM）

无需任何 API Key，启动内置 Mock 服务器即可立即体验：

```bash
# 终端 1：启动 Mock LLM 服务器
uv run mock-server

# 终端 2：评估任意本地仓库
uv run evaluate /path/to/your/repo
```

> Mock 服务器返回模板数据，评分结果仅用于验证流程是否正常，不反映真实质量。

### 3. 接入真实 LLM（推荐）

支持任何 OpenAI 兼容接口。以 MiniMax 为例：

```bash
LLM_BASE_URL=https://api.minimaxi.com/v1 \
LLM_API_KEY=your-api-key \
LLM_MODEL=MiniMax-M2.5 \
uv run evaluate /path/to/your/repo
```

也可通过 `--llm-url` / `--llm-key` / `--model` 参数传入：

```bash
uv run evaluate /path/to/your/repo \
  --llm-url https://api.minimaxi.com/v1 \
  --llm-key your-api-key \
  --model MiniMax-M2.5
```

### 4. 保存报告

```bash
# 保存 JSON 格式报告
uv run evaluate /path/to/your/repo --output report.json

# 显示详细 AutoGen 对话日志
uv run evaluate /path/to/your/repo --verbose
```

### 5. 检查服务器状态

```bash
uv run evaluate check-server
# 或指定自定义地址
uv run evaluate check-server --url http://localhost:8000
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_BASE_URL` | `http://localhost:8000/v1` | OpenAI 兼容 API 地址 |
| `LLM_API_KEY` | `mock-key-not-needed` | API 密钥 |
| `LLM_MODEL` | `mock-gpt-4` | 模型名称 |

---

## 项目结构

```
src/agentic_evaluator/
├── main.py               # CLI 入口（typer）
├── config.py             # LLM 客户端配置
├── agents/
│   ├── dimension_agents.py   # D1–D5 维度 Agent
│   └── orchestrator.py       # 评估编排与报告生成
└── skills/
    ├── file_scanner.py       # 文件系统扫描
    ├── code_analyzer.py      # 代码质量分析（多语言）
    ├── git_analyzer.py       # Git 历史与 CI 分析
    └── lang_analyzer.py      # Go/Java/Vue/SQL 专项分析
mock_server/
└── server.py                 # FastAPI Mock OpenAI 服务器
```

## 开发

```bash
# 运行测试
uv run pytest

# 运行单个测试
uv run pytest tests/test_xxx.py -v
```
