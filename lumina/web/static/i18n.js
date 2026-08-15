/* i18n - client-side translations.
   zh-CN strings in code / HTML are the baseline keys; the `en` dict maps them
   to English. `t()` falls back to the key itself (i.e. Chinese) when no
   translation exists. Language is driven by `settings.language` (app.js calls
   setLang() after loading settings); the last selected value is cached in
   localStorage so the UI renders correctly before settings load. */
var LUMINA_I18N = (function () {
  "use strict";
  var EN = {
    "展开 / 收起侧边栏": "Expand / Collapse Sidebar",
    "工作区": "Workspace",
    "选择 / 管理工作区": "Select / Manage Workspace",
    "会话": "Sessions",
    "搜索会话…": "Search sessions…",
    "文件树": "File Tree",
    "新建会话": "New Session",
    "重命名": "Rename",
    "导出 Markdown": "Export Markdown",
    "删除会话": "Delete Session",
    "自动批准": "Auto Approve",
    "切换主题": "Toggle Theme",
    "设置": "Settings",
    "终端": "Terminal",
    "关闭终端 (Ctrl+W)": "Close Terminal (Ctrl+W)",
    "输入命令，Enter 运行": "Type a command, Enter to run",
    "描述任务，例如：帮我修复失败的测试": "Describe a task, e.g. help me fix the failing tests",
    "发送": "Send",
    "添加图片": "Attach image",
    "移除图片": "Remove image",
    "最多添加 4 张图片": "Up to 4 images per message",
    "仅支持图片文件": "Only image files are supported",
    "图片超过 4MB": "Image exceeds 4MB",
    "需要密码": "Password Required",
    "此服务器需要密码才能访问": "This server requires a password to access",
    "密码": "Password",
    "密码错误，请重试": "Incorrect password, please try again",
    "登录": "Sign in",
    "会话用量": "Session Usage",
    "用量趋势": "Usage Trend",
    "关闭": "Close",

    "偏好设置自动保存到本地，重启后仍会保留。": "Preferences are saved locally and persist after restart.",
    "桌面": "Desktop",
    "MCP": "MCP",
    "技能": "Skills",
    "服务器": "Servers",
    "模型": "Models",
    "通用": "General",
    "语言": "Language",
    "更改 LuminaCode 的显示语言 *": "Change LuminaCode's display language *",
    "简体中文": "Chinese (Simplified)",
    "繁体中文": "Chinese (Traditional)",
    "English": "English",
    "权限请求将被自动批准": "Permission requests are auto-approved",
    "终端 shell": "Terminal shell",
    "选择终端使用的 shell。兼容的 shell 也会用于智能体工具调用 *": "Select the shell used by the terminal. Compatible shells are also used for agent tool calls *",
    "自动（默认）": "Auto (default)",
    "显示推理摘要": "Show reasoning summary",
    "在时间线中显示模型推理摘要，即思考过程": "Show the model's reasoning summary (thinking) in the timeline",
    "展开 shell 工具部分": "Expand shell tool sections",
    "在时间线中展开 shell 工具部分": "Expand shell tool sections in the timeline",
    "展开编辑工具部分": "Expand edit tool sections",
    "在时间线中展开 write_file、edit_file 等工具部分": "Expand write_file, edit_file and similar tool sections in the timeline",
    "右键菜单快捷入口": "Right-click menu shortcuts",
    "在文件夹右键菜单添加「在此打开 lumina chat」与「无限模式」入口（需先开启命令行入口）": "Add \"Open lumina chat here\" and \"Unlimited mode\" entries to the folder right-click menu (requires the CLI entry first)",
    "命令行入口": "CLI entry",
    "安装命令行": "Install CLI",
    "移除": "Remove",
    "外观": "Appearance",
    "配色方案": "Color scheme",
    "选择跟随系统、浅色或深色主题": "Follow system, light or dark theme",
    "系统": "System",
    "浅色": "Light",
    "深色": "Dark",
    "主题": "Theme",
    "自定义 LuminaCode 的主题": "Customize LuminaCode's theme",
    "界面字体": "UI font",
    "自定义整个界面使用的字体（留空为 System Sans）": "Custom font for the whole UI (empty = System Sans)",
    "代码字体": "Code font",
    "自定义代码块使用的字体（留空为 System Sans）": "Custom font for code blocks (empty = System Sans)",
    "终端字体": "Terminal font",
    "自定义终端使用的字体（留空为 JetBrainsMono Nerd Font Mono）*": "Custom font for the terminal (empty = JetBrainsMono Nerd Font Mono) *",
    "系统通知": "System notifications",
    "智能体": "Agent",
    "当智能体完成或需要注意时显示系统通知": "Show system notifications when the agent finishes or needs attention",
    "权限": "Permission",
    "当需要权限时显示系统通知": "Show system notifications when permission is required",
    "错误": "Error",
    "发生错误时显示系统通知": "Show system notifications when an error occurs",
    "音效": "Sounds",
    "当智能体完成或需要注意时播放声音 *": "Play a sound when the agent finishes or needs attention *",
    "无": "None",
    "柔和": "Soft",
    "清脆": "Chime",
    "错误音": "Error tone",
    "当需要权限时播放声音": "Play a sound when permission is required",
    "发生错误时播放声音": "Play a sound when an error occurs",
    "更新": "Updates",
    "发行说明": "Release notes",
    "更新后显示“新功能”弹窗 *": "Show the \"What's new\" popup after an update *",
    "检查更新": "Check for updates",
    "检查 GitHub 上的最新版本，发现新版本时可一键跳转下载": "Check the latest release on GitHub and jump to download when a new version is available",
    "高级": "Advanced",
    "在侧栏显示当前工作区的文件树面板": "Show the current workspace's file tree panel in the sidebar",
    "命令面板": "Command palette",
    "按 Ctrl+K 打开命令面板": "Press Ctrl+K to open the command palette",
    "服务器状态": "Server status",
    "在标题栏中显示服务器状态按钮 *": "Show a server status button in the title bar *",
    "自定义智能体": "Custom agents",
    "在输入框中显示智能体选择器 *": "Show an agent selector in the input box *",
    "快捷键": "Shortcuts",
    "打开设置": "Open Settings",
    "搜索项目": "Search project",
    "关闭终端": "Close Terminal",
    "切换终端": "Toggle Terminal",
    "新建终端": "New Terminal",
    "Prompt": "Prompt",
    "Shell": "Shell",

    "MCP 服务器": "MCP servers",
    "注册外部工具服务器（stdio）。配置写入应用数据目录，重启/新会话后生效。": "Register external tool servers (stdio). Config is saved under the app data directory and takes effect after a restart / new session.",
    "添加服务器": "Add server",
    "技能位于应用数据目录对应工作区的 <code>skills</code> 子目录，或全局 <code>~/.config/lumina/skills</code>。当输入命中触发词时自动注入提示。": "Skills live in the <code>skills</code> subfolder of the workspace's app-data directory, or in <code>~/.config/lumina/skills</code> (global). A skill is injected automatically when input matches its triggers.",
    "服务器列表": "Server list",
    "连接远程 LuminaCode 服务器。*：当前仅保存配置，尚未实现远程连接。": "Connect to remote LuminaCode servers. *: currently only saves config; remote connection is not implemented yet.",
    "模型列表": "Model list",
    "默认使用 DeepSeek V4 Flash。可切换到任意 OpenAI 兼容服务（OpenAI / Ollama / vLLM …）。初次使用请点击 ··· 配置 API Key。": "Uses DeepSeek V4 Flash by default. You can switch to any OpenAI-compatible service (OpenAI / Ollama / vLLM …). On first use, click ··· to configure the API Key.",

    "填写要连接的服务器的信息。密码会被保存到本地状态文件。": "Fill in the info of the server you want to connect to. The password is stored in a local state file.",
    "服务器 URL": "Server URL",
    "服务器名称（可选）": "Server name (optional)",
    "用户名（可选）": "Username (optional)",
    "密码（可选）": "Password (optional)",
    "密码": "Password",
    "取消": "Cancel",
    "保存": "Save",

    "配置模型": "Configure model",
    "修改将写入工作区 <code>.env</code> 文件。保存后新会话生效；运行中的任务不受影响。": "Changes are written to the <code>.env</code> file in the workspace. New sessions use the new config; running tasks are unaffected.",
    "提供商 (LUMINA_LLM_PROVIDER)": "Provider (LUMINA_LLM_PROVIDER)",
    "auto — 有 OPENAI_API_KEY 用 OpenAI，否则 DeepSeek": "auto - uses OpenAI if OPENAI_API_KEY is set, otherwise DeepSeek",
    "openai（任意 OpenAI 兼容服务：OpenAI / Ollama / vLLM …）": "openai (any OpenAI-compatible service: OpenAI / Ollama / vLLM …)",
    "API Key": "API Key",
    "未配置 API Key — 请在上方填写后保存": "No API Key configured - fill it in above and save",
    "高级参数": "Advanced parameters",
    "模型 (DEEPSEEK_MODEL)": "Model (DEEPSEEK_MODEL)",
    "规划模型 (DEEPSEEK_PLANNER_MODEL)": "Planner model (DEEPSEEK_PLANNER_MODEL)",
    "OpenAI 模型 (OPENAI_MODEL)": "OpenAI model (OPENAI_MODEL)",
    "OpenAI 规划模型 (OPENAI_PLANNER_MODEL)": "OpenAI planner model (OPENAI_PLANNER_MODEL)",
    "单次请求输出上限 (LUMINA_MAX_TOKENS ≤8192)": "Max output tokens per request (LUMINA_MAX_TOKENS ≤8192)",
    "任务累计预算 (LUMINA_TOKEN_BUDGET)": "Task budget (LUMINA_TOKEN_BUDGET)",
    "无限模式：不限制迭代轮数与 token 预算 (0)": "Unlimited mode: no iteration or token budget limits (0)",
    "最大迭代 (LUMINA_MAX_ITERATIONS)": "Max iterations (LUMINA_MAX_ITERATIONS)",
    "温度 (LUMINA_TEMPERATURE)": "Temperature (LUMINA_TEMPERATURE)",
    "启用 Reasoner 规划 (LUMINA_ENABLE_PLANNER)": "Enable Reasoner planning (LUMINA_ENABLE_PLANNER)",
    "上下文压缩 (LUMINA_COMPRESSION)": "Context compression (LUMINA_COMPRESSION)",
    "完成时自我审查 (LUMINA_SELF_REVIEW)": "Self-review on completion (LUMINA_SELF_REVIEW)",
    "TDD 模式：先写测试再实现 (LUMINA_TDD)": "TDD mode: write tests first, then implement (LUMINA_TDD)",
    "项目记忆：用 AGENTS.md 记录约定 (LUMINA_PROJECT_MEMORY)": "Project memory: use AGENTS.md to record conventions (LUMINA_PROJECT_MEMORY)",
    "多模态图片输入：发送图片给视觉模型 (LUMINA_VISION)": "Multimodal image input: send images to a vision model (LUMINA_VISION)",

    "选择工作区": "Select workspace",
    "切换要使用的项目目录。添加的工作区会保存到 <code>LUMINA_WORKSPACES</code>，下次启动仍可选用。": "Switch the project directory in use. Added workspaces are saved to <code>LUMINA_WORKSPACES</code> and remain available next launch.",
    "添加工作区": "Add workspace",
    "输入项目目录的绝对路径": "Enter the absolute path of the project directory",
    "选择文件夹": "Select folder",
    "浏览…": "Browse…",
    "添加": "Add",

    "添加 MCP 服务器": "Add MCP server",
    "服务器通过 stdio 启动。命令通常为 <code>python</code> / <code>npx</code>，参数如 <code>server.py</code>。": "Servers are launched over stdio. The command is usually <code>python</code> / <code>npx</code>, with arguments like <code>server.py</code>.",
    "名称": "Name",
    "命令": "Command",
    "参数（逗号分隔）": "Arguments (comma-separated)",
    "环境变量（可选，K=V 每行一个）": "Environment variables (optional, one K=V per line)",

    "启用命令行 lumina": "Enable the lumina CLI",
    "未检测到命令行 <code>lumina</code>。添加后即可在终端中使用 <code>lumina chat</code>、<code>lumina run \"…\"</code> 等指令，文件夹右键菜单也能直接使用。": "The <code>lumina</code> CLI was not detected. Once added you can use <code>lumina chat</code>, <code>lumina run \"…\"</code> and more in the terminal, and it is also available in the folder right-click menu.",
    "暂时不用": "Not now",
    "添加命令行功能": "Add CLI feature",

    "输入命令…": "Type a command…",
    "↑↓ 选择 · Enter 执行 · Esc 关闭": "↑↓ select · Enter run · Esc close",

    "停止": "Stop",
    "加载趋势…": "Loading trend…",
    "暂无用量数据": "No usage data yet",
    "会话 #": "Session #",
    "加载失败": "Load failed",
    "暂无用量数据。运行一次任务后，这里会显示 token 消耗与费用估算。": "No usage data yet. After running a task, token usage and cost estimates will show here.",
    "令牌": "Tokens",
    "总 tokens": "Total tokens",
    "输入 / 输出": "Input / Output",
    "推理 / 缓存": "Reasoning / Cache",
    "活动": "Activity",
    "消息数": "Messages",
    "用户": "user",
    "助手": "assistant",
    "工具": "tool",
    "迭代 / 工具调用": "Iterations / Tool calls",
    "费用": "Cost",
    "费用估算": "Estimated cost",
    "/1M tokens": "/1M tokens",
    "时间": "Time",
    "创建 / 更新": "Created / Updated",
    "费用为估算值，按总量 ¥2 / 1M tokens 计算，不代表最终账单。": "Cost is an estimate at ¥2 / 1M tokens and does not represent the final bill.",

    "复制": "Copy",
    "编辑": "Edit",
    "重新发送": "Resend",
    "重新生成": "Regenerate",
    "[copied] 已复制": "[copied] Copied",
    "正在编辑该消息，发送后将从此处重写对话": "Editing this message; sending will rewrite the conversation from here",
    "对话 ": "Conversation ",
    "已读取 ": "Read ",
    " 个文件": " files",
    "已读取 {n} 个文件": "Read {n} files",
    "调用 ": "Used ",
    " 个技能": " skills",
    "调用 {n} 个技能": "Called {n} skills",
    "已编辑 ": "Edited ",
    "已编辑 {p} +{a} -{r}": "Edited {p} +{a} -{r}",
    "工具操作": "Tool operations",
    "已思考 {s} 秒": "Thinking for {s} s",
    "需要批准": "Approval required",
    "需要批准: ": "Approval required: ",
    "批准": "Approve",
    "拒绝": "Reject",
    "[已批准] ": "[Approved] ",
    "[已拒绝] ": "[Rejected] ",
    "（已达累计 token 预算，可在 .env 调大或移除 LUMINA_TOKEN_BUDGET，0 为不限制）": "(reached the cumulative token budget; raise or remove LUMINA_TOKEN_BUDGET in .env, 0 = unlimited)",
    "（已达最大迭代次数，可在 .env 调大或移除 LUMINA_MAX_ITERATIONS，0 为不限制）": "(reached the max iterations; raise or remove LUMINA_MAX_ITERATIONS in .env, 0 = unlimited)",
    "继续执行（断点续跑）": "Continue (resume from checkpoint)",
    "正在继续…": "Continuing…",
    "[continue] 断点续跑中…": "[continue] Resuming from checkpoint…",
    "任务完成": "Task complete",
    "迭代 ": "Iterations ",
    " · 工具 ": " · tools ",
    " · tokens ": " · tokens ",
    "迭代 {i} · 工具 {t} · tokens {tok}": "Iteration {i} · tools {t} · tokens {tok}",
    "[stopped] 任务已手动停止": "[stopped] Task stopped manually",
    "任务已停止": "Task stopped",
    "已手动停止": "Stopped manually",
    "错误: ": "Error: ",
    "发生错误": "Error occurred",
    "(无输出)": "(no output)",
    "当前待办": "Current todo",
    "（{done}/{total}）：": "({done}/{total}): ",
    "今天": "Today",
    "昨天": "Yesterday",
    "本周": "This week",
    "更早": "Earlier",
    "没有匹配的消息": "No matching messages",
    "搜索失败": "Search failed",
    "新的会话标题": "New session title",
    "确定删除会话 #{id} 吗？该操作不可恢复。": "Delete session #{id}? This cannot be undone.",
    "已保存": "Saved",
    "保存失败: ": "Save failed: ",
    "需先开启命令行入口才能使用右键菜单": "Enable the CLI entry first to use the right-click menu",
    "右键菜单开关失败: ": "Failed to toggle right-click menu: ",
    "未检测到命令行 lumina，点击「安装命令行」即可在终端使用 lumina 指令": "The lumina CLI was not found. Click \"Install CLI\" to use the lumina command in your terminal",
    "命令行入口已安装（lumina.cmd），重启终端后生效": "CLI entry installed (lumina.cmd); restart your terminal to use it",
    "命令行 lumina 可用": "lumina CLI is available",
    "安装失败: ": "Install failed: ",
    "请重试": "Please retry",
    "正在添加…": "Adding…",
    "已添加，重启终端后即可使用。": "Added; restart your terminal to use it.",
    "添加失败: ": "Add failed: ",
    "添加失败，请重试。": "Add failed, please retry.",
    "MCP 可用，配置文件：": "MCP available, config file: ",
    "MCP 依赖未安装（pip install lumina[mcp]）。配置仍可保存，但工具不会连接。": "MCP dependency not installed (pip install lumina[mcp]). Config is still saved, but tools won't connect.",
    "尚未配置任何 MCP 服务器。": "No MCP servers configured yet.",
    "(无命令)": "(no command)",
    "未找到技能。可在以下目录创建 <code>&lt;name&gt;/skill.md</code>：": "No skills found. Create <code>&lt;name&gt;/skill.md</code> in:",
    "触发: ": "Triggers: ",
    "查看指令": "View instructions",
    "收起": "Collapse",
    "切换工作区": "Switch Workspace",
    "展开 / 收起侧边栏": "Expand / Collapse Sidebar",
    "刷新文件树": "Refresh File Tree",
    "尚未添加服务器。点击右上角“添加服务器”进行添加。": "No servers added yet. Click \"Add server\" in the top right to add one.",
    "编辑": "Edit",
    "删除": "Delete",
    "确定删除服务器 {name} ？": "Delete server {name}?",
    "编辑服务器": "Edit server",
    "名称和命令不能为空": "Name and command cannot be empty",
    "保存失败": "Save failed",
    "OpenAI 兼容模型": "OpenAI-compatible model",
    "已配置 OpenAI 兼容 Key": "OpenAI-compatible key configured",
    "已配置 DeepSeek API Key": "DeepSeek API key configured",
    "未配置 API Key，点击 ··· 配置": "No API key, click ··· to configure",
    "配置": "Configure",
    "已保存到 .env，新会话将使用新配置。": "Saved to .env; new sessions will use the new config.",
    "正在检查…": "Checking…",
    "无法获取最新版本号。": "Could not fetch the latest version number.",
    "已是最新版本 (v": "Up to date (v",
    "当前 v": "Currently v",
    "，发现新版本 ": ", a new version is available: ",
    "当前 v{cur}，发现新版本 {ver}：": "Currently v{cur}, a new version is available: {ver}",
    "前往 GitHub 下载": "Go to GitHub to download",
    "检查失败: ": "Check failed: ",
    "导出失败": "Export failed",
    "导出失败: ": "Export failed: ",
    "尚未配置工作区，请在下方添加一个项目目录。": "No workspace configured yet. Add a project directory below.",
    "（当前）": " (current)",
    "切换": "Switch",
    "当前环境无法弹出文件夹选择器，请手动输入绝对路径。": "A folder picker is not available in this environment. Enter the absolute path manually.",
    "请输入目录路径。": "Enter a directory path.",
    "已添加。": "Added.",
    "已删除。": "Deleted.",
    "删除失败: ": "Delete failed: ",
    "加载中…": "Loading…",
    "（空目录）": "(empty directory)",
    "文件预览 · ": "File preview · ",
    "（截断）": "(truncated)",
    "── {path}{trunc} ──": "── {path}{trunc} ──",
    "预览失败: ": "Preview failed: ",
    "终端 · ": "Terminal · ",
    "运行中…": "Running…",
    "❯ ": "❯ ",

    "默认智能体": "Default agent",
    "通用编码助手：阅读、编辑、运行命令、搜索与调试。": "General coding assistant: read, edit, run commands, search and debug.",
    "本地服务器": "Local server",
    "运行中": "Running",
    "未运行": "Not running",
    "已配置服务器": "Configured servers",
    "未连接": "Not connected",
    "尚未配置服务器，请在「设置 → 服务器」中添加。": "No servers configured yet. Add one in Settings → Servers.",
    "版本": "Version",
    "检查状态": "Check status",
    "正在检查服务器状态…": "Checking server status…",
    "新功能": "What's new",
    "继续使用": "Got it",
    "服务器状态不可用": "Server status unavailable",
    "启动时检测命令行 lumina，不可用时在设置按钮上显示红点提示": "LuminaCode checks for the lumina CLI at startup; if it is missing, a red dot appears on the settings button",
    "# v{ver}\n\n## 修复\n- 修复「新功能」弹窗每次启动都弹出的问题，现在只在升级后的首次启动显示\n- 修复桌面窗口无法打开而回退到浏览器的问题，WebView 数据改为持久化存储\n- 完善多语言翻译与文案一致性": "# v{ver}\n\n## Fixes\n- Fixed the release-notes popup showing on every launch; it now appears only on the first launch after an update\n- Fixed the desktop window failing to open and falling back to the browser; WebView data is now stored persistently\n- Polished translations and wording consistency",
  };

  var cacheKey = "lumina-i18n-lang";
  var current = "zh-CN";
  try {
    var cached = localStorage.getItem(cacheKey);
    if (cached === "en" || cached === "zh-CN") current = cached;
  } catch (e) {}

  function t(s) {
    if (current === "en" && EN[s] != null) return EN[s];
    return s;
  }

  function tpl(s, args) {
    var out = t(s);
    if (args) out = out.replace(/\{(\w+)\}/g, function (m, k) {
      return args[k] != null ? String(args[k]) : m;
    });
    return out;
  }

  function applyText(sel, attr, setter) {
    var els = document.querySelectorAll(sel);
    for (var i = 0; i < els.length; i++) {
      var k = els[i].getAttribute(attr);
      if (k) setter(els[i], t(k));
    }
  }

  // Translate only the leading text node of an element so that any child
  // elements (e.g. the session count <span>) are preserved. Surrounding
  // whitespace is kept so layout does not shift.
  function applyTextNode(el) {
    var key = el.getAttribute("data-i18n");
    var nodes = el.childNodes;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n.nodeType !== 3) continue;
      var original = n.data || "";
      var trimmed = original.trim();
      if (!trimmed) continue;
      var translated = t(key);
      var lead = original.slice(0, original.indexOf(trimmed));
      var trail = original.slice(original.indexOf(trimmed) + trimmed.length);
      n.data = lead + translated + trail;
      return;
    }
  }

  function apply() {
    applyText("[data-i18n]", "data-i18n", applyTextNode);
    applyText("[data-i18n-html]", "data-i18n-html", function (el, v) { el.innerHTML = v; });
    applyText("[data-i18n-placeholder]", "data-i18n-placeholder", function (el, v) { el.placeholder = v; });
    applyText("[data-i18n-title]", "data-i18n-title", function (el, v) { el.title = v; });
    applyText("[data-i18n-aria]", "data-i18n-aria", function (el, v) { el.setAttribute("aria-label", v); });
    try {
      document.documentElement.lang = current === "en" ? "en" : "zh-CN";
    } catch (e) {}
  }

  function setLang(lang) {
    current = lang === "en" ? "en" : "zh-CN";
    try { localStorage.setItem(cacheKey, current); } catch (e) {}
  }

  return {
    setLang: setLang,
    t: t,
    tpl: tpl,
    apply: apply,
    current: function () { return current; },
  };
})();
