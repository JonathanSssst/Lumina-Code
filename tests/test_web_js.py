from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "lumina" / "web" / "static" / "app.js"

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
  setTimeout, clearTimeout };
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
  currentSession: 5, activeWorkspace: "" };
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
  busy: false };
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
  startThinkTimer() { ctx.thinkTimerStarted = true; }
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
