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
  if (/^function /.test(lines[i]) && !lines[i].includes("renderTodos")) { e = i; break; }
}
function mkEl() {
  return { className: "", textContent: "", innerHTML: "", children: [], hidden: false,
    classList: { _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); },
      contains(c) { return this._s.has(c); } },
    appendChild(c) { this.children.push(c); return c; } };
}
const bar = mkEl();
const ctx = { document: { getElementById: id => (id === "todobar" ? bar : null), createElement: () => mkEl() } };
vm.createContext(ctx);
vm.runInContext(lines.slice(s, e).join("\n"), ctx);
let failed = 0;
function check(name, cond) { if (!cond) { failed++; console.log("FAIL " + name); } else console.log("ok " + name); }
ctx.renderTodos([]);
check("empty hides", bar.hidden === true);
ctx.renderTodos([
  { content: "step one", status: "in_progress" },
  { content: "step two", status: "completed" },
  { content: "step three" }
]);
check("shown", bar.hidden === false);
check("head row", bar.children[0] && bar.children[0].className === "todo-head");
const count = bar.children[0].children.find(c => c.className === "todo-count");
check("progress count", count && count.textContent === "1 / 3 已完成");
const body = bar.children[1];
check("one row per todo", body && body.children.length === 3);
check("numbered text", body.children[0].children[1].textContent === "1. step one");
check("completed styling", body.children[1].className.indexOf("completed") !== -1);
check("collapsed by default", !bar.classList.contains("open"));
bar.classList.add("open");
ctx.renderTodos([{ content: "x", status: "pending" }, { content: "y", status: "completed" }]);
check("keeps open state", bar.classList.contains("open"));
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
