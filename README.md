# LuminaCode

一个本地运行的自主编码 Agent，基于 DeepSeek V4 Flash，提供 CLI、Web 与桌面三种使用方式。
支持多会话持久化、Reasoner 分层规划、MCP 服务器、技能（Skills）、上下文压缩与自我反思闭环。

## 特性

- **自主执行闭环**：探索 → 规划 → 执行 → 测试 → 自修复 → 自我审查
- **三界面**：CLI（`lumina run` / `lumina chat`）、Web UI（Markdown 渲染、Thinking 折叠、工具调用卡片、多会话管理）与桌面应用（pywebview 原生窗口）
- **深色 / 浅色主题**：一键切换，偏好本地记忆（默认深色）
- **设置面板**：Web UI 内直接编辑 `.env`（API Key、token 预算、模型等），保存后新会话生效
- **多工作区**：内置工作区管理器，可浏览 / 添加 / 删除 / 切换任意项目目录，会话与数据库按工作区隔离，并记住上次使用的工作区
- **安全分级**：白名单命令自动放行，危险命令（`rm -rf`、`git push` 等）需人工批准，未知命令需批准
- **Reasoner 分层规划**：`deepseek-reasoner` 规划，flash 模型执行
- **并行子 agent**：`run_parallel` 工具将任务拆给多个只读子 agent 并发探索，合并结果
- **上下文压缩**：长任务接近 token 预算时自动摘要早期历史，防止中断
- **自我反思**：完成时自动审查结果，发现缺陷继续修复
- **AGENTS.md**：工作区根目录的 `AGENTS.md` / `agents.md` 自动注入为项目指令
- **撤销与导出**：文件写入前自动快照，`undo_file` 一键回滚；会话可导出 Markdown / JSON
- **会话持久化**：SQLite 存储，CLI/Web 均可随时恢复
- **MCP 与技能**：支持 MCP 服务器接入与本地技能库
- **版本自检**：启动时检测 GitHub 最新发布版，发现新版本可一键跳转下载

## 安装

```bash
git clone https://github.com/JonathanSssst/Lumina-Code.git
cd Lumina-Code
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

### 命令行（CLI）

```bash
# 查看版本
lumina -version
# 或
lumina --version

# 单次任务
lumina run "修复失败的测试"

# 自动批准所有操作（只建议在可信沙箱中）
lumina run "重构 main.py" --yes

# 交互式多会话聊天
lumina chat
# 会话内命令：/new /list /resume <id> /delete <id> /exit

# 环境诊断（查看生效配置、API 连通性等）
lumina doctor
```

### 桌面应用

#### 方式一：源码运行

```bash
python app.py            # 启动桌面窗口（pywebview）
python app.py --no-webview   # 改为在浏览器中打开
python app.py --port 1300    # 指定起始端口（端口被占用时自动向后扫描）
```

#### 方式二：打包的 exe（推荐日常使用）

从 GitHub [Releases](https://github.com/JonathanSssst/Lumina-Code/releases) 下载最新的
`LuminaCode.exe`（免安装单文件），双击即可打开桌面窗口。

- 首次启动默认工作区为项目根目录；点击顶栏文件夹按钮可打开「选择工作区」面板，
  浏览并添加任意项目目录，随时切换。下次启动会自动恢复上次使用的工作区。
- 配置、工作区列表与运行状态保存在 `%APPDATA%\LuminaCode`
  （可用环境变量 `LUMINA_HOME` 覆盖）。
- 启动时自动检查 GitHub 最新版本，发现新版本会在顶栏显示更新角标。

### Web UI（CLI 方式）

```bash
lumina web                 # 默认打开桌面 WebView 窗口，http://127.0.0.1:1200
lumina web --no-webview    # 改为在浏览器中打开
lumina web --port 9000     # 指定端口
```

Web UI 特性：

- 新建 / 删除 / 重命名会话，会话自动持久化
- 工作区选择：顶栏下拉切换，或打开「选择工作区」面板浏览 / 添加 / 删除项目目录（桌面窗口可用原生文件夹选择器）
- 发送后「发送」按钮变为「停止」，回复结束后自动恢复
- 会话导出（Markdown / JSON 下载）
- 深色 / 浅色主题一键切换（默认深色，本地记忆）
- ⚙ 设置面板：直接编辑 `.env`（API Key、Base URL、模型、token 预算、迭代上限、温度、规划 / 压缩 / 自我审查开关），保存后新会话生效
- Markdown 渲染（代码块、标题、列表、表格、分割线、引用、链接）
- 思考过程（Thinking）折叠面板，显示「已思考 N 秒」；对话结束前不显示复制等消息操作
- 工具操作汇总卡片：显示「已读取 N 个文件 · 已编辑 path +n -m」等，可点击展开详情
- 右侧悬浮对话导航（圆点轨）：当前会话居中放大，鼠标悬浮显示会话标题与内容，滚轮可快速浏览并在停止后自动回到当前会话
- 「自动批准」开关：勾选后所有待批准操作直接放行
- 按 `↑`/`↓` 浏览历史输入

## 打包为桌面程序（PyInstaller）

一键构建（安装依赖 → 运行测试 → PyInstaller 打包 → 启动冒烟测试）：

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

手动等价命令：

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name LuminaCode --icon assets\icon.ico --add-data "assets\icon.ico;assets" --hidden-import webview.platforms.winforms --hidden-import webview.platforms.win32 --hidden-import webview.platforms.edgechromium --hidden-import webview.platforms.mshtml --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module matplotlib --exclude-module PIL --exclude-module tkinter app.py
```

打包后运行 `LuminaCode.exe` 即为桌面软件；配置、工作区列表与运行状态
保存在 `%APPDATA%\LuminaCode`（可用环境变量 `LUMINA_HOME` 覆盖）。

GitHub 上推送 `v*` 标签会自动触发 CI（`.github/workflows/build-release.yml`）：
在 Windows runner 上运行测试 + 打包，并把 `LuminaCode.exe` 上传到对应 Release。

## 架构

```
app.py                # 桌面应用入口（pywebview + 内嵌 HTTP 服务），打包入口
lumina/
├── cli.py             # Typer CLI 入口（run/chat/web/doctor/-version）
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
