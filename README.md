# LuminaCoder

一个本地运行的自主编码 Agent，基于 DeepSeek V4 Flash，提供 CLI 与 Web 双界面。
支持多会话持久化、Reasoner 分层规划、MCP 服务器、技能（Skills）、上下文压缩与自我反思闭环。

## 特性

- **自主执行闭环**：探索 → 规划 → 执行 → 测试 → 自修复 → 自我审查
- **双界面**：CLI（`lumina run` / `lumina chat`）与 Web UI（Markdown 渲染、Thinking 折叠、工具调用卡片、多会话管理）
- **桌面 WebView 窗口**：`lumina web` 默认以系统 WebView 弹出桌面窗口（可 `--no-webview` 退回浏览器）
- **深色 / 浅色主题**：一键切换，偏好本地记忆（默认浅色）
- **设置面板**：Web UI 内直接编辑 `.env`（API Key、token 预算、模型等），保存后新会话生效
- **多工作区**：一个 Web 实例可切换多个工作目录，会话与数据库按工作区隔离
- **安全分级**：白名单命令自动放行，危险命令（`rm -rf`、`git push` 等）需人工批准，未知命令需批准
- **Reasoner 分层规划**：`deepseek-reasoner` 规划，flash 模型执行
- **并行子 agent**：`run_parallel` 工具将任务拆给多个只读子 agent 并发探索，合并结果
- **上下文压缩**：长任务接近 token 预算时自动摘要早期历史，防止中断
- **自我反思**：完成时自动审查结果，发现缺陷继续修复
- **AGENTS.md**：工作区根目录的 `AGENTS.md` / `agents.md` 自动注入为项目指令
- **撤销与导出**：文件写入前自动快照，`undo_file` 一键回滚；会话可导出 Markdown / JSON
- **会话持久化**：SQLite 存储，CLI/Web 均可随时恢复
- **MCP 与技能**：支持 MCP 服务器接入与本地技能库

## 安装

```bash
git clone https://github.com/JonathanSssst/Lumina-Coder.git
cd Lumina-Coder
pip install -e ".[web,dev]"
```

可选组件：

```bash
pip install -e ".[mcp]"       # MCP 服务器支持
pip install -e ".[webview]"   # 桌面 WebView 窗口（lumina web 默认使用；Windows 10/11 自带 WebView2）
```

## 配置

复制 `.env.example` 为 `.env` 并填入 API Key：

```bash
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

常用配置（全部可选）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LUMINA_TOKEN_BUDGET` | `30000` | 单任务累计 token 预算 |
| `LUMINA_MAX_TOKENS` | `8192` | 单次请求输出上限（API 上限内自动收敛） |
| `LUMINA_MAX_ITERATIONS` | `20` | 最大循环轮数 |
| `LUMINA_ENABLE_PLANNER` | `false` | 开启 Reasoner 分层规划 |
| `LUMINA_DEEPSEEK_PLANNER_MODEL` | `deepseek-reasoner` | 规划模型 |
| `LUMINA_COMPRESSION` | `true` | 上下文压缩开关 |
| `LUMINA_SELF_REVIEW` | `true` | 完成时自我审查 |
| `LUMINA_DANGER_COMMANDS` | `rm -rf,git push,...` | 危险命令（需批准） |
| `LUMINA_SAFE_COMMANDS` | `pytest,ruff,...` | 安全命令（自动放行） |
| `LUMINA_WORKSPACES` | — | 附加工作区（逗号分隔），`lumina web` 中可切换 |

运行 `lumina doctor` 查看当前生效配置。

## 使用

### CLI

```bash
# 单次任务
lumina run "修复失败的测试"

# 自动批准所有操作（只建议在可信沙箱中）
lumina run "重构 main.py" --yes

# 交互式多会话聊天
lumina chat
# 会话内命令：/new /list /resume <id> /delete <id> /exit
```

### Web UI

```bash
lumina web                 # 默认打开桌面 WebView 窗口，http://127.0.0.1:1200
lumina web --no-webview    # 改为在浏览器中打开
lumina web --port 9000     # 指定端口
```

Web UI 特性：

- 新建 / 删除 / 重命名会话，会话自动持久化
- 多工作区切换（`LUMINA_WORKSPACES` 配置额外工作区）
- 任务可随时「停止」
- 会话导出（Markdown / JSON 下载）
- 深色 / 浅色主题一键切换（默认浅色，本地记忆）
- ⚙ 设置面板：直接编辑 `.env`（API Key、Base URL、模型、token 预算、迭代上限、温度、规划 / 压缩 / 自我审查开关），保存后新会话生效
- Markdown 渲染（代码块、标题、列表、引用、链接）
- 思考过程（Thinking）折叠面板
- 工具调用卡片可点击展开查看参数与结果
- 「自动批准」开关：勾选后所有待批准操作直接放行
- 按 `↑`/`↓` 浏览历史输入

## 架构

```
lumina/
├── cli.py             # Typer CLI 入口（run/chat/web/doctor）
├── config.py          # 环境变量配置（.env）
├── config_edit.py     # .env 安全读写（设置面板后端）
├── factory.py         # Agent/工具注册组装
├── agent/
│   ├── loop.py        # 主循环：执行、压缩、自修复、自我审查
│   ├── budget.py      # token/迭代预算
│   ├── authorize.py   # 批准器与 Hooks
│   └── ...            
├── llm/client.py      # DeepSeek 流式客户端
├── tools/             # 文件、搜索、shell、git、web、并行子 agent 工具
├── context/           # 项目上下文扫描
├── web/app.py         # FastAPI + WebSocket UI
├── store.py           # SQLite 会话存储
├── logging_setup.py   # 日志持久化（.lumina/lumina.log）
├── mcp/               # MCP 客户端
└── skills/            # 技能加载器
```

## 工具集

`read_file` / `write_file` / `edit_file` / `replace_all` / `undo_file` / `list_files` / `list_tree` /
`glob` / `grep` / `run_command` / `run_tests` / `git_status` / `git_diff` / `git_log` /
`web_search` / `web_fetch` / `run_parallel`（并行子 agent，仅读写工具）

## 开发

```bash
pip install -e ".[dev]"
python -m pytest -q
ruff check lumina tests
```

## 许可证

MIT
