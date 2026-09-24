# 自动化测试智能体（Auto Test Agent）

该项目已升级为可用于前端、后端、数据库联动验证的自动化测试智能体：

1. 输入来源（网站 URL / 需求文档 / PRD / 任意文本）
2. 自动产出测试用例
3. 规划动作点（页面动作 / API / DB）
4. 执行（mock / Playwright 真浏览器 / MCP HTTP）
5. 核对结果并生成结构化报告
6. 任务入库、历史查询、HTML 报告与证据输出

## 核心能力

- Playwright 真浏览器执行器（支持截图证据）
- API 调用断言（状态码与响应片段）
- DB 只读校验（仅允许 SELECT/WITH，支持 SQLite / PostgreSQL / MySQL）
- SQLite 任务与运行历史存储
- 并发 worker 队列 + 失败重试
- FastAPI 后端接口
- HTML 报告页（`/runs/{id}/report.html`）

## 安装

```bash
python3 -m pip install -e ".[dev]"
```

如需 Playwright 真浏览器执行：

```bash
python3 -m pip install -e ".[playwright]"
python3 -m playwright install chromium
```

如需 PostgreSQL / MySQL 只读校验：

```bash
python3 -m pip install -e ".[db]"
```

## CLI 使用

### Mock 执行模式（默认）

```bash
auto-test-agent \
  --source "系统需要支持用户登录并支持商品搜索" \
  --runtime-mode mock \
  --output report.json
```

### Playwright 执行模式

```bash
auto-test-agent \
  --source "https://example.com" \
  --runtime-mode playwright \
  --base-url "https://example.com" \
  --storage-state-path ".state/user.json" \
  --artifacts-dir "artifacts" \
  --output report.json
```

使用数据库 URL（query_db 动作会默认读取）：

```bash
auto-test-agent \
  --source "系统需要支持数据库查询" \
  --runtime-mode playwright \
  --db-url "postgresql://user:pass@127.0.0.1:5432/appdb" \
  --output report.json
```

### 走真实 MCP HTTP

```bash
auto-test-agent \
  --source "系统需要支持用户登录" \
  --mcp-endpoint "https://mcp.example.internal/execute" \
  --mcp-token "YOUR_TOKEN" \
  --output report.json
```

### 兼容旧模式（命令式测试）

```bash
auto-test-agent --cmd "python3 -m pytest -q" --output report.json
```

## 后端服务

启动 API 服务：

```bash
auto-test-agent-api
```

默认地址：`http://127.0.0.1:8000`

### 常用接口

- `POST /tasks`：创建任务（可自动执行）
- `GET /tasks`：任务列表
- `POST /tasks/{task_id}/runs`：执行任务
- `POST /tasks/{task_id}/run-jobs`：加入异步队列
- `GET /tasks/{task_id}/runs`：运行历史
- `GET /runs/{run_id}`：运行详情
- `GET /runs/{run_id}/report`：报告 JSON
- `GET /runs/{run_id}/report.html`：报告页面
- `GET /run-jobs` / `GET /run-jobs/{job_id}`：查询队列任务状态

示例（创建并执行）：

```bash
curl -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "source": "系统需要支持用户登录并支持商品搜索",
    "runtime_mode": "mock",
    "auto_run": true,
    "auto_run_async": true,
    "max_attempts": 3
  }'
```

## URL 安全控制（防 SSRF）

- 默认阻断 `localhost`、`*.local`、内网地址
- 可通过 `--allow-private-url` 放开（仅建议受控网络）
- 可通过 `--allowed-domain` 多次传入域名白名单

## 测试

```bash
python3 -m pytest -q
```
