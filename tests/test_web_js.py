from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "lumina" / "web" / "static" / "app.js"
I18N_JS = Path(__file__).resolve().parent.parent / "lumina" / "web" / "static" / "i18n.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").split("\n");
const s = lines.findIndex(l => l.includes("function esc"));
const e = lines.findIndex(l => l.includes("DOM helpers"));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(lines.slice(s, e).join("\n"), ctx);
const cases = [
  ["link", "see [docs](https://example.com/x)", '<a href="https://example.com/x"'],
  ["bold", "**hi** there", "<strong>hi</strong>"],
  ["heading", "# Title", "<h1>Title</h1>"],
  ["code-inline", "run `pip install x`", "<code>pip install x</code>"],
  ["code-fence", "```py\nprint(1)\n```", "<pre><code>"],
  ["ul", "- a\n- b", "<ul>"],
  ["ol", "1. a\n2. b", "<ol>"],
  ["hr", "---", "<hr/>"],
  ["table", "a|b\n-|-\n1|2", "<table>"],
  ["crlf", "line1\r\nline2", "line1"],
];
let failed = 0;
for (const [name, input, needle] of cases) {
  const out = ctx.renderMarkdown(input);
  if (!out.includes(needle)) { failed++; console.log("FAIL " + name, JSON.stringify(out)); }
  else console.log("ok " + name);
}
process.exit(failed ? 1 : 0);
"""


_TODO_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").split("\n");
const s = lines.findIndex(l => l.startsWith("const TODO_ICON"));
let e = -1;
for (let i = s + 1; i < lines.length; i++) {
  if (lines[i].startsWith("function switchWorkspace")) { e = i; break; }
}
function mkEl() {
  return { className: "", textContent: "", innerHTML: "", children: [], hidden: false, style: {},
    classList: { _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); },
      contains(c) { return this._s.has(c); } },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener() {}, offsetWidth: 0 };
}
const bar = mkEl();
bar.hidden = true; // matches the `hidden` attribute in index.html
const ctx = { document: { getElementById: id => (id === "todobar" ? bar : null), createElement: () => mkEl() },
  setTimeout, clearTimeout, t: s => s, tpl: (s, a) => s.replace(/\{(\w+)\}/g, (m, k) => (a && a[k] != null) ? String(a[k]) : m) };
vm.createContext(ctx);
vm.runInContext(lines.slice(s, e).join("\n"), ctx);
let failed = 0;
function check(name, cond) { if (!cond) { failed++; console.log("FAIL " + name); } else console.log("ok " + name); }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
(async () => {
  ctx.renderTodos([]);
  check("empty hides", bar.hidden === true);
  ctx.renderTodos([
    { content: "step one", status: "in_progress" },
    { content: "step two", status: "completed" },
    { content: "step three" }
  ]);
  check("shown", bar.hidden === false);
  const card = bar.children[0];
  check("card built", card && card.className === "todo-card");
  const head = card.children[0], body = card.children[1];
  check("head has spinner + label + chevron", head.children.length === 4 &&
    head.children[1].className === "todo-label");
  const count = head.children[1].children[0];
  check("count format (done/total)", count.textContent === "（1/3）：");
  await sleep(250);
  check("current todo text", head.children[2].textContent === "step one");
  check("one row per todo", body.children.length === 3);
  check("numbered text", body.children[0].children[1].textContent === "1. step one");
  check("completed styling", body.children[1].className.indexOf("completed") !== -1);
  check("collapsed by default", !bar.classList.contains("open"));
  bar.classList.add("open");
  ctx.renderTodos([
    { content: "next task", status: "in_progress" },
    { content: "last", status: "completed" }
  ]);
  check("keeps open state", bar.classList.contains("open"));
  check("count updates", count.textContent === "（1/2）：");
  await sleep(250);
  check("smooth switch to next todo", head.children[2].textContent === "next task");
  ctx.renderTodos([]);
  await sleep(300);
  check("smoothly hides when last todo done", bar.hidden === true && bar.innerHTML === "");
  process.exit(failed ? 1 : 0);
})();
"""


_USAGE_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").split("\n");
const s = lines.findIndex(l => l.startsWith("const USAGE_RING_C"));
const e = lines.findIndex(l => l.includes("function scrollBottom"));
function mkEl() {
  const el = { className: "", textContent: "", title: "", style: {}, hidden: false, children: [],
    _q: {}, setAttribute(a, v) { if (a === "class") el.className = v; el[a] = v; },
    appendChild(c) { el.children.push(c); return c; },
    classList: { _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c, force) { force === undefined ? (this._s.has(c) ? this._s.delete(c) : this._s.add(c)) :
        (force ? this._s.add(c) : this._s.delete(c)); },
      contains(c) { return this._s.has(c); } },
    querySelector(sel) { return el._q[sel] || null; } };
  return el;
}
const btn = mkEl(), val = mkEl(), pop = mkEl(), body = mkEl(), barEl = mkEl();
btn._q[".usage-ring-bar"] = barEl;
const els = { usageRingBtn: btn, usageRingVal: val, usagePop: pop, usagePopBody: body };
const ctx = { document: {
    getElementById: id => els[id] || null,
    createElement: () => mkEl(),
    createElementNS: () => mkEl() },
  fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({
      id: 5, title: "t", context_limit: 1000, messages: 2,
      counts: { user: 1, assistant: 1, tool: 0 },
      usage: { total: 400, prompt: 300, completion: 100, reasoning: 10, cached: 20 },
      iterations: 2, tool_calls: 1, cost: { value: 0.0008, rate_per_m: 2 },
      created_at: "2026-01-01", updated_at: "2026-01-01" }) }),
  currentSession: 5, activeWorkspace: "", t: s => s, tpl: (s, a) => s.replace(/\{(\w+)\}/g, (m, k) => (a && a[k] != null) ? String(a[k]) : m) };
vm.createContext(ctx);
vm.runInContext(lines.slice(s, e).join("\n"), ctx);
let failed = 0;
function check(name, cond) { if (!cond) { failed++; console.log("FAIL " + name); } else console.log("ok " + name); }
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  ctx.updateUsageRing(null);
  check("no data shows dash", val.textContent === "–");
  check("no data marks ring empty", btn.classList.contains("none"));
  ctx.toggleUsagePop();
  check("popup opens", pop.hidden === false);
  await sleep(5);
  check("ring value formatted", val.textContent === "400");
  const off = parseFloat(barEl.style.strokeDashoffset);
  check("ring offset in range", off > 0 && off <= 119.38);
  check("ring bar cleared of none", !btn.classList.contains("none"));
  check("ring title set", val.title === "total 400 / 1000");
  check("popup body rendered", body.children.length === 3);
  const hero = body.children[0], rows = body.children[1], hint = body.children[2];
  check("hero built", hero && hero.className === "usage-hero");
  check("ring wrap has no center number", hero.children[0].children.length === 1);
  const svg = hero.children[0].children[0];
  check("svg ring built", svg && svg.className === "usage-ring-svg");
  const info = hero.children[1];
  check("hero info has title+sub+bar", info.children.length === 3);
  check("hero sub text", info.children[1].textContent === "400 / 1.0k tokens · 40%");
  const fill = info.children[2].children[0];
  check("progress bar fill width", fill.style.width === "40%");
  const dataRows = rows.children.filter(c => c.className === "usage-row");
  check("one row per stat", dataRows.length === 7);
  check("section labels present", rows.children.some(c => c.className === "usage-sec" && c.textContent === "令牌"));
  const totalRow = dataRows[0];
  check("total label", totalRow.children[0].textContent === "总 tokens");
  check("total hl value", totalRow.children[1].className.indexOf("hl") !== -1);
  check("dim suffix separate", totalRow.children[1].children[0].className === "dim" &&
    totalRow.children[1].children[0].textContent === " / 1.0k");
  check("hint present", hint && hint.className === "usage-hint");
  ctx.toggleUsagePop();
  check("popup closes", pop.hidden === true);
  ctx.currentSession = 0;
  ctx.toggleUsagePop();
  check("popup reopens", pop.hidden === false);
  await sleep(5);
  check("no session clears stats", val.textContent === "–" && btn.classList.contains("none"));
  ctx.toggleUsagePop();
  check("closes again", pop.hidden === true);
  process.exit(failed ? 1 : 0);
})();
"""


_ACTIONS_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").split("\n");
const s = lines.findIndex(l => l.includes("function actionBtn"));
const e = lines.findIndex(l => l.includes("function flashNote"));
let attached = [];
function mkEl(cls) {
  const el = { className: cls || "", textContent: "", children: [], onclick: null, parent: null,
    classList: { _s: new Set((cls || "").split(" ")), contains(c) { return this._s.has(c); } },
    appendChild(c) { c.parent = el; el.children.push(c); if (c.className === "msg-actions") attached.push(c); return c; },
    remove() { attached = attached.filter(x => x !== el);
      if (el.parent) el.parent.children = el.parent.children.filter(x => x !== el); } };
  return el;
}
const msgs = [mkEl("msg user"), mkEl("msg assistant"), mkEl("msg user")];
const ctx = { document: {
    createElement: () => mkEl(),
    querySelectorAll: sel => (sel.indexOf(".msg-actions") !== -1 ? attached.slice() : msgs) },
  busy: false, t: s => s };
vm.createContext(ctx);
vm.runInContext(lines.slice(s, e).join("\n"), ctx);
let failed = 0;
function check(name, cond) { if (!cond) { failed++; console.log("FAIL " + name); } else console.log("ok " + name); }
ctx.refreshMsgActions();
check("actions only on last message",
  msgs[2].children.length === 1 && msgs[0].children.length === 0 && msgs[1].children.length === 0);
check("action class", msgs[2].children[0].className === "msg-actions");
check("user actions: copy+edit+resend", msgs[2].children[0].children.length === 3);
ctx.busy = true;
ctx.refreshMsgActions();
check("busy clears all actions", msgs.every(m => m.children.length === 0));
ctx.busy = false;
ctx.refreshMsgActions();
check("re-attached on last", msgs[2].children.length === 1);
process.exit(failed ? 1 : 0);
"""

_THINK_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").split("\n");
const s = lines.findIndex(l => l.includes("function ensureThinking"));
const e = lines.findIndex(l => l.includes("/* ---------- websocket"));
function mkEl() {
  const el = {
    className: "", innerHTML: "", open: true, children: [],
    appendChild(c) { el.children.push(c); return c; },
    querySelector(sel) { return el._q && el._q[sel] ? el._q[sel] : null; }
  };
  return el;
}
const logEl = mkEl();
const spanMock = mkEl();
let created = [], call = 0;
const ctx = {
  document: { createElement: () => {
    const el = mkEl();
    call++;
    if (call === 2) el._q = { span: spanMock };
    created.push(el);
    return el;
  } },
  log: logEl,
  thinkingEl: null, thinkBuf: null, thinkSpan: null,
  startThinkTimer() { ctx.thinkTimerStarted = true; },
  t: s => s, tpl: (s, a) => s.replace(/\{(\w+)\}/g, (m, k) => (a && a[k] != null) ? String(a[k]) : m)
};
vm.createContext(ctx);
vm.runInContext(lines.slice(s, e).join("\n"), ctx);
let failed = 0;
function check(name, cond) {
  if (!cond) { failed++; console.log("FAIL " + name); }
  else console.log("ok " + name);
}
const tb = ctx.ensureThinking();
const det = logEl.children[0];
check("block appended once", logEl.children.length === 1);
check("details collapsed thinking", det.className === "thinking" && det.open === false);
check("summary has timer span", det.children[0].innerHTML.includes("已思考 0 秒"));
check("body el created", tb === det.children[1] && tb.className === "think-body");
check("timer span captured", ctx.thinkSpan === spanMock);
check("timer started", ctx.thinkTimerStarted === true);
check("buf reset", ctx.thinkBuf === "");
check("reuse same block", ctx.ensureThinking() === tb && logEl.children.length === 1);
process.exit(failed ? 1 : 0);
"""


def test_app_js_has_valid_syntax():
    r = subprocess.run(["node", "--check", str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr


def test_render_markdown_core_cases():
    r = subprocess.run(["node", "-e", _HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


def test_render_todos_collapsible_read_only():
    r = subprocess.run(["node", "-e", _TODO_HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


def test_usage_ring_and_stats_popup():
    r = subprocess.run(["node", "-e", _USAGE_HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


def test_msg_actions_only_on_last_message():
    r = subprocess.run(["node", "-e", _ACTIONS_HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


def test_thinking_block_collapsible():
    r = subprocess.run(["node", "-e", _THINK_HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


_FEATURES_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").split("\n");
const find = (sub, from) => lines.findIndex((l, i) => i >= from && l.includes(sub));
const slice = (s, e) => lines.slice(s, e).join("\n");
let failed = 0;
function check(name, cond) { if (!cond) { failed++; console.log("FAIL " + name); } else console.log("ok " + name); }

const docEl = { _a: {}, setAttribute(k, v) { this._a[k] = v; }, removeAttribute(k) { delete this._a[k]; } };
const settings = { color_scheme: "dark", theme: "tokyonight",
  notif_agent: true, notif_permission: true, notif_error: false,
  sound_agent: "none", sound_permission: "none", sound_error: "none" };
let notifCalls = [];
const Notif = function (t) { notifCalls.push(t); };
Notif.permission = "granted";
const ctx = {
  settings,
  document: { documentElement: docEl },
  localStorage: { _m: {}, setItem(k, v) { this._m[k] = v; }, getItem(k) { return this._m[k] || null; } },
  window: { matchMedia: () => ({ matches: true }), Notification: Notif },
  Notification: Notif,
  updateThemeBtn() {}, newSession() {}, openWsManager() {}, openSettings() {},
  toggleTerminal() {}, toggleSidebar() {}, loadFileTree() {}, showFileTreePanel() {}, checkUpdate() {},
  t: s => s,
};
vm.createContext(ctx);

vm.runInContext(slice(find("function applyTheme", 0), find("function toggleTheme", 0)), ctx);
ctx.applyTheme();
check("named theme applied", docEl._a["data-theme-style"] === "tokyonight");
check("scheme dark", docEl._a["data-theme"] === "dark");
settings.theme = "system";
ctx.applyTheme();
check("system theme removes style", !("data-theme-style" in docEl._a));

vm.runInContext(slice(find("function playSound", 0), find("function isTypingTarget", 0)), ctx);
ctx.notifyUser("任务完成", "迭代 1", "agent");
check("notification created", notifCalls.length === 1 && notifCalls[0] === "任务完成");
ctx.notifyUser("err", "boom", "error");
check("error gate respected", notifCalls.length === 1);
settings.notif_agent = false;
ctx.notifyUser("x", "y", "agent");
check("agent gate respected", notifCalls.length === 1);

vm.runInContext(slice(find("function paletteCommands", 0), find("function togglePalette", 0)), ctx);
const titles = ctx.paletteCommands().map(c => c.title);
check("palette has new session", titles.includes("新建会话"));
check("palette has terminal", titles.includes("切换终端"));
check("palette has settings", titles.includes("打开设置"));
process.exit(failed ? 1 : 0);
"""


def test_theme_notifications_and_palette_helpers():
    r = subprocess.run(["node", "-e", _FEATURES_HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


_BATCH2_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").split("\n");
const find = (sub, from) => lines.findIndex((l, i) => i >= from && l.includes(sub));
const slice = (s, e) => lines.slice(s, e).join("\n");
let failed = 0;
function check(name, cond) { if (!cond) { failed++; console.log("FAIL " + name); } else console.log("ok " + name); }

const ctx = { t: s => s, tpl: (s, a) => s.replace(/\{(\w+)\}/g, (m, k) => (a && a[k] != null) ? String(a[k]) : m) };
vm.createContext(ctx);
vm.runInContext(slice(find("const SESSION_GROUPS", 0), find("function runSessionSearch", 0)), ctx);
function iso(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
  String(d.getDate()).padStart(2, "0") + " 10:00:00"; }
const now = new Date();
const todayStr = iso(now);
const yest = new Date(now.getTime() - 86400000);
const monday = new Date(now);
monday.setDate(now.getDate() - ((now.getDay() + 6) % 7));
if (iso(monday) === todayStr) monday.setDate(monday.getDate() - 7);
const longAgo = new Date(now.getTime() - 30 * 86400000);
check("today group", ctx.sessionGroupOf(todayStr) === "today");
check("yesterday group", ctx.sessionGroupOf(iso(yest)) === "yesterday");
check("week group", ctx.sessionGroupOf(iso(monday)) === "week");
check("earlier group", ctx.sessionGroupOf(iso(longAgo)) === "earlier");
check("missing date", ctx.sessionGroupOf("") === "earlier");
check("garbage date", ctx.sessionGroupOf("not-a-date") === "earlier");

vm.runInContext(slice(find("function fileRefFrag", 0), find("function paintFileRef", 0)), ctx);
check("frag after @", ctx.fileRefFrag("看看 @src/main.py") === "src/main.py");
check("frag mid-word no trigger", ctx.fileRefFrag("email@domain.com") === "");
check("frag after space", ctx.fileRefFrag("编辑 @ README.md") === "");
check("frag empty", ctx.fileRefFrag("hello ") === "");
const files = ctx.fileRefFiles([
  { type: "dir", children: [{ type: "file", path: "a.py" }, { type: "dir", children: [{ type: "file", path: "b/c.py" }] }] },
  { type: "file", path: "d.md" }
]);
check("flatten files", files.join(",") === "a.py,b/c.py,d.md");
process.exit(failed ? 1 : 0);
"""


def test_session_grouping_and_file_ref_helpers():
    r = subprocess.run(["node", "-e", _BATCH2_HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


_FEATURES2_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").split("\n");
const find = (sub, from) => lines.findIndex((l, i) => i >= from && l.includes(sub));
const slice = (s, e) => lines.slice(s, e).join("\n");
let failed = 0;
function check(name, cond) { if (!cond) { failed++; console.log("FAIL " + name); } else console.log("ok " + name); }

function mkEl() {
  return { value: "", textContent: "", innerHTML: "", hidden: true, className: "", children: [],
    _q: {},
    addEventListener() {},
    appendChild(c) { this.children.push(c); return c; },
    classList: { _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c, force) { force === undefined ? (this._s.has(c) ? this._s.delete(c) : this._s.add(c)) :
        (force ? this._s.add(c) : this._s.delete(c)); },
      contains(c) { return this._s.has(c); } } };
}
const els = {
  agentSel: mkEl(), agentSelWrap: mkEl(), serverStatusBtn: mkEl(), serverStatusPop: mkEl(),
  serverStatusBody: mkEl(), releaseOverlay: mkEl(), releaseBody: mkEl(),
};
const FEAT_T = {
  "# v{ver}\n\n## 修复\n- 修复「新功能」弹窗每次启动都弹出的问题，现在只在升级后的首次启动显示\n- 修复桌面窗口无法打开而回退到浏览器的问题，WebView 数据改为持久化存储\n- 完善多语言翻译与文案一致性": "# v{ver}\n\n## Fixes\n- Fixed the release-notes popup showing on every launch; it now appears only on the first launch after an update\n- Fixed the desktop window failing to open and falling back to the browser; WebView data is now stored persistently\n- Polished translations and wording consistency",
  "本地服务器": "Local server",
  "服务器状态不可用": "Server status unavailable",
  "尚未配置服务器，请在「设置 → 服务器」中添加。": "No servers configured yet. Add one under Settings > Servers.",
};
const ctx = {
  settings: { release_notes: true, custom_agents: true, server_status: true },
  currentSession: 3,
  APP_VERSION: "1.0.6",
  t: s => FEAT_T[s] || s,
  tpl: (s, a) => String(FEAT_T[s] || s).replace(/\{(\w+)\}/g, (m, k) => (a && a[k] != null) ? String(a[k]) : m),
  document: { getElementById(id) { return els[id] || null; }, createElement: () => mkEl() },
  localStorage: { _m: {}, setItem(k, v) { this._m[k] = v; }, getItem(k) { return k in this._m ? this._m[k] : null; } },
  sessionStorage: { _m: {}, setItem(k, v) { this._m[k] = v; }, getItem(k) { return k in this._m ? this._m[k] : null; } },
  fetch(url) {
    if (url === "/api/health") return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, version: "1.0.6", local: true }) });
    if (url === "/api/servers") return Promise.resolve({ ok: true, json: () => Promise.resolve({ servers: [{ name: "r1", url: "http://r1" }] }) });
    if (url === "/api/agents") return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [{ id: "default", name: "默认智能体" }, { id: "x", name: "X" }] }) });
    return Promise.resolve({ ok: false });
  },
};
vm.createContext(ctx);
vm.runInContext(slice(find("server status button + popup", 0), find("---------- servers ----------", 0)), ctx);

(async () => {
  ctx.toggleServerStatus();
  check("server popup opens", els.serverStatusPop.hidden === false);
  await new Promise(r => setTimeout(r, 5));
  check("local + one remote row", els.serverStatusBody.children.length === 2);
  check("local row shows running", els.serverStatusBody.children[0].children[1].textContent === "运行中");
  check("remote row lists url", els.serverStatusBody.children[1].children[0].children[1].textContent === "http://r1");
  check("btn dot on when local ok", els.serverStatusBtn.classList.contains("on"));
  ctx.toggleServerStatus();
  check("server popup closes", els.serverStatusPop.hidden === true);

  ctx.openReleaseNotes();
  check("release body rendered", els.releaseBody.innerHTML.indexOf("# v1.0.6") === 0);
  check("release overlay open", els.releaseOverlay.classList.contains("open"));
  ctx.closeReleaseNotes();
  check("release overlay closed", !els.releaseOverlay.classList.contains("open"));
  check("last seen persisted", ctx.localStorage.getItem("lumina-release-last-seen") === "1.0.6");
  ctx.maybeShowReleaseNotes();
  check("no re-show after seen", !els.releaseOverlay.classList.contains("open"));
  ctx.localStorage.setItem("lumina-release-last-seen", "0.0.0");
  ctx.maybeShowReleaseNotes();
  check("re-show after version bump", els.releaseOverlay.classList.contains("open"));
  ctx.closeReleaseNotes();

  await ctx.loadAgents();
  check("agent options populated", els.agentSel.children.length === 2);
  check("agent wrap shown when enabled", els.agentSelWrap.hidden === false);
  ctx.persistAgent();
  check("agent persisted per session", ctx.sessionStorage.getItem("lumina-agent-3") !== null);
  process.exit(failed ? 1 : 0);
})();
"""


def test_server_status_release_notes_and_agent_selector():
    r = subprocess.run(["node", "-e", _FEATURES2_HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


_I18N_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const els = [];
function mkTextNode(data) { return { nodeType: 3, data }; }
function mkEl(key, text) {
  const el = { nodeType: 1, childNodes: [mkTextNode(text)],
    getAttribute(a) { return a === "data-i18n" ? key : null; } };
  els.push(el);
  return el;
}
const store = {};
const ctx = {
  localStorage: { getItem: k => store[k] || null, setItem: (k, v) => { store[k] = String(v); } },
  document: { querySelectorAll: sel => (sel === "[data-i18n]" ? els.slice() : []),
    documentElement: { lang: "" } },
};
vm.createContext(ctx);
vm.runInContext(src, ctx);
const i18n = vm.runInContext("LUMINA_I18N", ctx);
let failed = 0;
function check(name, cond) { if (!cond) { failed++; console.log("FAIL " + name); } else console.log("ok " + name); }
const el = mkEl("设置", "设置");
const pad = mkEl("会话", " 会话 ");
const miss = mkEl("未收录的键", "未收录的键");
i18n.setLang("zh-CN");
i18n.apply();
check("initial zh is key", el.childNodes[0].data === "设置");
i18n.setLang("en");
i18n.apply();
check("en is English", el.childNodes[0].data === "Settings");
i18n.setLang("zh-CN");
i18n.apply();
check("back to zh is key again", el.childNodes[0].data === "设置");
i18n.setLang("en"); i18n.apply();
check("en keeps padding", pad.childNodes[0].data === " Sessions ");
i18n.setLang("zh-CN"); i18n.apply();
check("zh restores padded key", pad.childNodes[0].data === " 会话 ");
i18n.setLang("en"); i18n.apply();
check("untranslated en keeps key", miss.childNodes[0].data === "未收录的键");
i18n.setLang("zh-CN"); i18n.apply();
check("untranslated zh keeps key", miss.childNodes[0].data === "未收录的键");
check("lang cached to localStorage", store["lumina-i18n-lang"] === "zh-CN");
process.exit(failed ? 1 : 0);
"""


def test_i18n_round_trip_between_languages():
    r = subprocess.run(["node", "-e", _I18N_HARNESS, str(I18N_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout


_IMG_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const file = process.argv[1];
const lines = fs.readFileSync(file, "utf8").split("\n");
const find = (sub, from) => lines.findIndex((l, i) => i >= from && l.includes(sub));
const slice = (s, e) => lines.slice(s, e).join("\n");
let failed = 0;
function check(name, cond) { if (!cond) { failed++; console.log("FAIL " + name); } else console.log("ok " + name); }
function mkEl() {
  const el = { className: "", textContent: "", innerHTML: "", src: "", dataset: {}, children: [],
    appendChild(c) { el.children.push(c); return c; },
    classList: { _s: new Set(), contains(c) { return this._s.has(c); } } };
  return el;
}
const logEl = mkEl();
const ctx = {
  document: { createElement: () => mkEl() },
  log: logEl,
  userCounter: 0,
  bulkLoading: false,
  busy: false,
  t: s => s,
  renderMarkdown: s => "<md>" + s + "</md>",
  scrollBottom: () => { ctx.scrolled = true; },
  rebuildToc: () => { ctx.tocCalled = true; },
  refreshMsgActions: () => { ctx.refreshCalled = true; },
  activeWorkspace: "", authToken: "",
};
vm.createContext(ctx);
vm.runInContext(slice(find("function renderMsgImages", 0), find("function actionBtn", 0)), ctx);
const u1 = "data:image/png;base64,AAA", u2 = "data:image/jpeg;base64,BBB";
check("renderMsgImages null for empty", ctx.renderMsgImages([]) === null && ctx.renderMsgImages(null) === null);
const inner = ctx.appendMd("user", "看图", false, [u1, u2]);
const div = logEl.children[0];
check("dataset.images stored as json", div.dataset.images === JSON.stringify([u1, u2]));
check("dataset.text kept", div.dataset.text === "看图");
const row = div.children[0];
check("image row first", row && row.className === "msg-images");
check("one img per url", row.children.length === 2 && row.children[0].src === u1 && row.children[1].src === u2);
check("markdown bubble second", div.children[1].className === "bubble markdown");
check("markdown rendered", div.children[1].innerHTML === "<md>看图</md>");
check("appended to log", logEl.children.length === 1);
check("user counter advanced", ctx.userCounter === 1);
check("scrolled", ctx.scrolled === true);
check("toc rebuilt for user", ctx.tocCalled === true);
check("actions refreshed", ctx.refreshCalled === true);
logEl.children.length = 0;
ctx.tocCalled = false; ctx.refreshCalled = false;
ctx.appendMd("assistant", "好的", true);
const aDiv = logEl.children[0];
check("assistant no images attr", aDiv.dataset.images === undefined && aDiv.children.length === 1);
check("no toc rebuild for assistant", ctx.tocCalled === false);
check("actions still refreshed", ctx.refreshCalled === true);

vm.runInContext(slice(find("function wsAuthPath", 0), find("function connectWS", 0)), ctx);
ctx.activeWorkspace = ""; ctx.authToken = "";
check("plain ws path", ctx.wsAuthPath() === "/ws");
ctx.authToken = "t0k";
check("token query", ctx.wsAuthPath() === "/ws?token=t0k");
ctx.activeWorkspace = "w s";
check("workspace + token encoded", ctx.wsAuthPath() === "/ws?w=w%20s&token=t0k");
process.exit(failed ? 1 : 0);
"""


def test_multimodal_message_render_and_ws_auth_path():
    r = subprocess.run(["node", "-e", _IMG_HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout
