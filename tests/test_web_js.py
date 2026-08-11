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


def test_app_js_has_valid_syntax():
    r = subprocess.run(["node", "--check", str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr


def test_render_markdown_core_cases():
    r = subprocess.run(["node", "-e", _HARNESS, str(APP_JS)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout
