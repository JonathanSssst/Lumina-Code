from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lumina.config import Settings, get_settings
from lumina.config_edit import write_env
from lumina.factory import build_agent
from lumina.store import SessionStore, default_db_path
from lumina.types import Message

_EDITABLE_KEYS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_PLANNER_MODEL",
    "LUMINA_MAX_TOKENS",
    "LUMINA_TOKEN_BUDGET",
    "LUMINA_MAX_ITERATIONS",
    "LUMINA_TEMPERATURE",
    "LUMINA_ENABLE_PLANNER",
    "LUMINA_COMPRESSION",
    "LUMINA_SELF_REVIEW",
)


def _config_payload(s: Settings) -> dict:
    payload: dict = {}
    for field_name, field in Settings.model_fields.items():
        alias = field.alias
        if alias in _EDITABLE_KEYS:
            payload[alias] = getattr(s, field_name)
    return payload

_INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>LuminaCode</title>
<script>
try { document.documentElement.setAttribute("data-theme", localStorage.getItem("lumina-theme") || "dark"); } catch (e) {}
</script>
<style>
  :root {
    /* Lumina — dark developer console (default) */
    --bg: #0a0a0e;
    --bg-grad: radial-gradient(1100px 560px at 82% -12%, rgba(245,177,61,.07), transparent 60%),
               radial-gradient(820px 480px at -5% 105%, rgba(94,197,216,.05), transparent 55%);
    --panel: #131318; --panel2: #1b1b22; --panel3: #21212b;
    --border: #26262f; --border-strong: #393946;
    --text: #ececf0; --muted: #9595a4; --faint: #6b6b78;
    --accent: #f5b13d; --accent-2: #fbd07a;
    --accent-soft: rgba(245,177,61,.14); --accent-line: rgba(245,177,61,.36);
    --user-grad: linear-gradient(135deg, #fbd07a, #e08a2b);
    --tool: #5ec5d8; --tool-soft: rgba(94,197,216,.13);
    --code-bg: #0c0c10; --code-text: #e6e6ec;
    --error-bg: #2a1216; --error-border: #7f1d1d; --error-text: #fca5a5;
    --thinking-bg: #0e0e13;
    --approval-bg: #241a05;
    --header-bg: rgba(10,10,14,.72);
    --ok: #34d399; --danger: #f87171;
    --on-accent: #1a1208;
    --mono: "JetBrains Mono", "SF Mono", "Cascadia Code", ui-monospace, Consolas, monospace;
    --sans: "PingFang SC", "Noto Sans SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    --font-ui: var(--sans);
    --font-code: var(--mono);
    --font-term: var(--mono);
    --shadow: 0 10px 34px rgba(0,0,0,.5);
  }
  [data-theme-style="matrix"] {
    --bg: #050503; --bg-grad: radial-gradient(1100px 560px at 82% -12%, rgba(0,255,102,.06), transparent 60%);
    --panel: #070805; --panel2: #0b0d08; --panel3: #10130b;
    --border: #173b1f; --border-strong: #2a5a30;
    --text: #33ff66; --muted: #20a64a; --faint: #14602e;
    --accent: #00ff66; --accent-2: #7dff9e;
    --accent-soft: rgba(0,255,102,.12); --accent-line: rgba(0,255,102,.38);
    --user-grad: linear-gradient(135deg, #7dff9e, #00c853);
    --tool: #00ffcc; --tool-soft: rgba(0,255,204,.12);
    --code-bg: #04070a; --code-text: #33ff66;
    --error-bg: #140505; --error-border: #5c1111; --error-text: #ff6b6b;
    --thinking-bg: #04070a; --approval-bg: #0a1408;
    --header-bg: rgba(5,5,3,.72);
    --ok: #34d399; --danger: #f87171; --on-accent: #04140a;
  }
  [data-theme="light"] {
    --bg: #f6f5f1;
    --bg-grad: radial-gradient(1100px 560px at 82% -12%, rgba(217,119,6,.09), transparent 60%),
               radial-gradient(820px 480px at -5% 105%, rgba(8,145,178,.06), transparent 55%);
    --panel: #ffffff; --panel2: #f1efe8; --panel3: #e9e6dc;
    --border: #e1ded2; --border-strong: #cbc7b8;
    --text: #1b1b20; --muted: #6a6a76; --faint: #9a9aa3;
    --accent: #c2710c; --accent-2: #d97706;
    --accent-soft: rgba(194,113,12,.10); --accent-line: rgba(194,113,12,.32);
    --user-grad: linear-gradient(135deg, #f0a014, #d97706);
    --tool: #0e7490; --tool-soft: rgba(14,116,144,.10);
    --code-bg: #f3f1ea; --code-text: #1b1b20;
    --error-bg: #fef2f2; --error-border: #f87171; --error-text: #b91c1c;
    --thinking-bg: #f7f6f1;
    --approval-bg: #fffbeb;
    --header-bg: rgba(246,245,241,.72);
    --ok: #059669; --danger: #dc2626;
    --on-accent: #1a1208;
    --shadow: 0 10px 34px rgba(70,55,15,.14);
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body { margin: 0; display: flex;
         background: var(--bg); background-image: var(--bg-grad); background-attachment: fixed;
         color: var(--text); font-family: var(--font-ui);
         -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
         transition: background-color .35s ease, color .35s ease; }
  ::selection { background: var(--accent-soft); color: var(--text); }

  /* ---------- brand mark ---------- */
  .brand-mark { width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center;
    background: linear-gradient(135deg, var(--accent-2), var(--accent));
    box-shadow: 0 0 0 1px rgba(245,177,61,.28), 0 6px 18px rgba(245,177,61,.22); }
  .brand-mark svg { width: 15px; height: 15px; }

  select, button, input { font-family: var(--font-ui); color: var(--text);
    background: var(--panel2); border: 1px solid var(--border); border-radius: 9px;
    padding: 7px 11px; font-size: 13px; outline: none;
    transition: border-color .18s ease, background .18s ease, transform .08s ease, box-shadow .18s ease, color .18s ease; }
  select { cursor: pointer; padding-right: 26px; appearance: none; -webkit-appearance: none;
    background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%),
                      linear-gradient(135deg, var(--muted) 50%, transparent 50%);
    background-position: calc(100% - 14px) 52%, calc(100% - 9px) 52%;
    background-size: 5px 5px; background-repeat: no-repeat; }
  select:hover, button:hover { border-color: var(--accent-line); }
  button { cursor: pointer; }
  button:active { transform: translateY(1px); }

  .icon-btn { width: 34px; height: 34px; padding: 0; display: grid; place-items: center;
    background: transparent; border: 1px solid transparent; border-radius: 8px; color: var(--muted); }
  .icon-btn:hover { background: var(--panel2); border-color: var(--border); color: var(--text); }
  .icon-btn svg { width: 17px; height: 17px; }
  .icon-btn.danger:hover { color: var(--danger); }
  #themeBtn .i-sun, #themeBtn .i-moon { width: 17px; height: 17px; }
  [data-theme="dark"] #themeBtn .i-sun { display: none; }
  [data-theme="dark"] #themeBtn .i-moon { display: block; }
  [data-theme="light"] #themeBtn .i-sun { display: block; }
  [data-theme="light"] #themeBtn .i-moon { display: none; }

  .toggle { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--muted);
    cursor: pointer; white-space: nowrap; user-select: none; }
  .toggle input { appearance: none; -webkit-appearance: none; width: 30px; height: 17px; margin: 0;
    background: var(--panel3); border: 1px solid var(--border-strong); border-radius: 999px;
    position: relative; cursor: pointer; transition: background .2s ease, border-color .2s ease; }
  .toggle input::after { content: ""; position: absolute; top: 1px; left: 1px; width: 13px; height: 13px;
    border-radius: 50%; background: var(--muted); transition: transform .2s ease, background .2s ease; }
  .toggle input:checked { background: var(--accent-soft); border-color: var(--accent-line); }
  .toggle input:checked::after { transform: translateX(12px); background: var(--accent); }

  .stat { color: var(--faint); font-size: 11.5px; font-family: var(--mono); letter-spacing: .2px;
    padding: 4px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--panel); }

  /* ---------- app layout ---------- */
  #app { flex: 1; display: flex; min-height: 0; min-width: 0; }
  #right { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
  #work { flex: 1; display: flex; min-height: 0; min-width: 0; }

  /* ---------- sidebar ---------- */
  #sidebar { width: 264px; flex: none; display: flex; flex-direction: column;
    background: var(--panel); border-right: 1px solid var(--border);
    overflow: hidden; transition: width .22s ease, transform .22s ease; z-index: 20; }
  .side-head { display: flex; align-items: center; gap: 8px; padding: 10px 12px;
    border-bottom: 1px solid var(--border); }
  .side-brand-txt { font-size: 13px; font-weight: 600; color: var(--muted); white-space: nowrap; }
  .side-section { padding: 14px 12px 6px; min-height: 0; }
  .side-grow { flex: 1; overflow-y: auto; padding-bottom: 10px; }
  .side-label { display: flex; align-items: center; justify-content: space-between;
    font-size: 11px; font-weight: 650; letter-spacing: .8px; text-transform: uppercase;
    color: var(--muted); margin-bottom: 8px; white-space: nowrap; }
  .side-label .cnt { color: var(--faint); font-weight: 500; letter-spacing: 0; }
  .side-ws { display: flex; gap: 8px; align-items: center; }
  .side-ws select { flex: 1; min-width: 0; }
  #sessionList { display: flex; flex-direction: column; }
  .session-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px;
    border-radius: 9px; cursor: pointer; margin-bottom: 2px;
    border: 1px solid transparent; transition: background .15s ease, border-color .15s ease; }
  .session-item:hover { background: var(--panel2); }
  .session-item.active { background: var(--accent-soft); border-color: var(--accent-line); }
  .session-item .si-dot { display: none; width: 8px; height: 8px; border-radius: 50%;
    background: var(--border-strong); flex: none; }
  .session-item.active .si-dot { background: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .session-item .si-title { flex: 1; min-width: 0; font-size: 12.5px; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  .session-item .si-meta { flex: none; font-size: 10.5px; color: var(--faint); font-family: var(--mono); }
  .side-actions { display: flex; gap: 6px; padding: 8px 12px; border-top: 1px solid var(--border); }
  .side-actions .icon-btn { flex: 1; width: auto; height: 32px; border: 1px solid var(--border);
    border-radius: 8px; background: var(--panel2); }
  .side-actions .icon-btn:hover { border-color: var(--accent-line); color: var(--text); }
  .side-foot { border-top: 1px solid var(--border); padding: 10px 12px;
    display: flex; flex-direction: column; gap: 10px; }
  .side-foot .stat { display: block; text-align: center; }
  .side-foot-btns { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .foot-icns { display: flex; gap: 4px; align-items: center; }

  /* ---------- sidebar collapsed ---------- */
  #sidebar.collapsed { width: 56px; }
  #sidebar.collapsed .brand-mark,
  #sidebar.collapsed .side-brand-txt,
  #sidebar.collapsed .side-label, #sidebar.collapsed .side-label .cnt,
  #sidebar.collapsed .si-title, #sidebar.collapsed .si-meta,
  #sidebar.collapsed .side-ws select, #sidebar.collapsed .toggle,
  #sidebar.collapsed .side-foot .stat { display: none; }
  #sidebar.collapsed .side-section { padding: 14px 10px 6px; }
  #sidebar.collapsed .side-ws { justify-content: center; }
  #sidebar.collapsed .session-item { justify-content: center; padding: 8px 0; }
  #sidebar.collapsed .session-item .si-dot { display: block; }
  #sidebar.collapsed .side-actions { flex-direction: column; padding: 8px 10px; }
  #sidebar.collapsed .side-actions .icon-btn { flex: none; width: 36px; height: 34px; margin: 0 auto; }
  #sidebar.collapsed .side-foot { align-items: center; }
  #sidebar.collapsed .side-foot-btns { flex-direction: column; gap: 6px; }
  #sidebar.collapsed .foot-icns { flex-direction: column; gap: 4px; }
  #sideToggle .i-close { display: none; }
  body.sidebar-hidden #sideToggle .i-open { display: none; }
  body.sidebar-hidden #sideToggle .i-close { display: block; }

  @media (max-width: 760px) {
    #app { position: relative; }
    #sidebar { position: absolute; top: 0; bottom: 0; left: 0; box-shadow: var(--shadow); }
    #sidebar.collapsed { transform: translateX(-100%); width: 264px; }
  }
  @media (max-width: 900px) {
    #toc { display: none; }
  }

  /* ---------- main / log ---------- */
  #main { flex: 1; overflow-y: auto; scroll-behavior: smooth; min-width: 0; }
  #log { max-width: 820px; margin: 0 auto; padding: 28px 22px 44px; }

  /* ---------- right floating conversation navigation (dot rail) ---------- */
  #toc { position: fixed; right: 16px; top: 50%; transform: translateY(-50%);
    height: 40vh; width: 26px; z-index: 40; pointer-events: none; }
  #tocDots { position: relative; width: 100%; height: 100%; overflow: hidden; pointer-events: auto; }
  .toc-dot { position: absolute; left: 50%; transform: translate(-50%, -50%); border-radius: 50%;
    background: var(--muted); cursor: pointer;
    transition: top .25s ease, width .2s ease, height .2s ease, opacity .2s ease, background .15s ease,
      box-shadow .15s ease; }
  .toc-dot:hover { background: var(--accent); }
  .toc-dot.active { background: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft); }
  .toc-tip { position: fixed; z-index: 60; max-width: 280px; padding: 8px 10px; font-size: 12px;
    line-height: 1.5; color: var(--text); background: var(--panel2);
    border: 1px solid var(--border-strong); border-radius: 8px; box-shadow: var(--shadow);
    opacity: 0; transition: opacity .12s ease; pointer-events: none; }
  .toc-tip-title { font-size: 11px; font-weight: 650; color: var(--accent); margin-bottom: 4px; }
  .toc-tip-body { white-space: pre-wrap; word-break: break-word; }

  .msg { margin-bottom: 16px; line-height: 1.65; font-size: 14px; word-break: break-word;
    animation: rise .32s ease both; }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  .msg .bubble { display: inline-block; padding: 10px 15px; border-radius: 15px; }
  .msg.user { display: flex; flex-direction: column; align-items: flex-end; }
  .msg.user .bubble { background: var(--user-grad); color: var(--on-accent);
    border-radius: 15px 15px 4px 15px; max-width: 85%; font-weight: 500;
    box-shadow: 0 6px 22px rgba(245,177,61,.18); }
  .msg.assistant .bubble { background: var(--panel); border: 1px solid var(--border);
    border-radius: 4px 15px 15px 15px; max-width: 100%; }
  .msg .markdown h1, .msg .markdown h2, .msg .markdown h3 { margin: .7em 0 .35em; line-height: 1.3; font-weight: 650; }
  .msg .markdown h1 { font-size: 18px; } .msg .markdown h2 { font-size: 16px; } .msg .markdown h3 { font-size: 14px; }
  .msg .markdown p { margin: .45em 0; }
  .msg .markdown hr { border: none; border-top: 1px solid var(--border-strong); margin: .7em 0; }
  .msg .markdown table { border-collapse: collapse; margin: .5em 0; font-size: 12.5px; width: 100%; }
  .msg .markdown th, .msg .markdown td { border: 1px solid var(--border); padding: 5px 9px; text-align: left; }
  .msg .markdown th { background: var(--panel2); font-weight: 600; }
  .msg .markdown ul, .msg .markdown ol { margin: .45em 0; padding-left: 22px; }
  .msg .markdown li { margin: .2em 0; }
  .msg .markdown code { background: var(--panel2); border: 1px solid var(--border); border-radius: 5px;
    padding: 1px 6px; font-family: var(--mono); font-size: 12.5px; color: var(--accent); }
  .msg.user .markdown code { background: rgba(0,0,0,.14); border-color: rgba(0,0,0,.14); color: var(--on-accent); }
  .msg.user .markdown a { color: var(--on-accent); border-color: rgba(0,0,0,.3); }
  .msg .markdown pre { background: var(--code-bg); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px 14px; overflow-x: auto; }
  .msg .markdown pre code { background: none; border: none; padding: 0; font-size: 12.5px; color: var(--code-text); }
  .msg .markdown blockquote { margin: .5em 0; padding: 4px 14px; border-left: 3px solid var(--accent);
    color: var(--muted); background: var(--accent-soft); border-radius: 0 8px 8px 0; }
  .msg .markdown a { color: var(--accent); text-decoration: none; border-bottom: 1px solid var(--accent-line); }
  .msg.error .bubble { background: var(--error-bg); border: 1px solid var(--error-border); color: var(--error-text); }
  .msg.stat { color: var(--faint); font-family: var(--mono); font-size: 11.5px; text-align: center;
    padding: 8px 0; border-top: 1px dashed var(--border); margin: 18px 0; }

  /* thinking */
  details.thinking { margin: 8px 0 16px; border: 1px solid var(--border); border-radius: 12px;
    background: var(--thinking-bg); overflow: hidden; }
  details.thinking summary { cursor: pointer; user-select: none; padding: 9px 14px;
    color: var(--muted); font-size: 12.5px; display: flex; gap: 8px; align-items: center;
    font-family: var(--mono); letter-spacing: .3px; transition: background .18s ease; }
  details.thinking summary:hover { background: var(--panel2); }
  details.thinking summary .think-ic { width: 14px; height: 14px; color: var(--accent); flex: none; }
  details.thinking[open] summary { border-bottom: 1px solid var(--border); }
  details.thinking .think-body { padding: 10px 14px 14px; font-size: 13px; color: var(--muted); line-height: 1.6; }
  details.thinking .think-body pre, details.thinking .think-body code { font-family: var(--mono); }

  /* tool card */
  .tool-card { margin: 6px 0 16px; border: 1px solid var(--border); border-radius: 11px;
    background: var(--panel); overflow: hidden; transition: border-color .18s ease; }
  .tool-card:hover { border-color: var(--border-strong); }
  .tool-card .tool-head { display: flex; gap: 9px; align-items: center; padding: 8px 12px;
    cursor: pointer; user-select: none; transition: background .15s ease; }
  .tool-card .tool-head:hover { background: var(--panel2); }
  .tool-card .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--tool); flex: none;
    box-shadow: 0 0 0 3px var(--tool-soft); }
  .tool-card .tname { color: var(--tool); font-family: var(--mono); font-size: 12px; font-weight: 600; }
  .tool-card .targs { color: var(--faint); font-size: 11.5px; font-family: var(--mono);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  .tool-card .ops-head { color: var(--tool); font-family: var(--mono); font-size: 12px; font-weight: 600; flex: 1; }
  .tool-card .chev { color: var(--faint); font-size: 11px; transition: transform .2s ease; }
  .tool-card.open .chev { transform: rotate(90deg); }
  .tool-card .tool-body { display: none; border-top: 1px solid var(--border); padding: 12px 14px;
    max-height: 320px; overflow: auto; background: var(--code-bg); }
  .tool-card .tool-body pre { margin: 0; white-space: pre-wrap; word-break: break-word;
    font-family: var(--mono); font-size: 12px; color: var(--code-text); line-height: 1.55; }
  .tool-card .tool-body pre.err { color: var(--danger); }
  .tool-card.err { border-color: var(--error-border); }
  .tool-card.err .dot { background: var(--danger); box-shadow: 0 0 0 3px rgba(248,113,113,.16); }
  .tool-card.err .tname { color: var(--danger); }
  .tool-card.err .ops-head { color: var(--danger); }

  /* approval */
  .approval { margin: 12px 0; padding: 12px 15px; border: 1px solid var(--accent-line);
    border-radius: 12px; background: linear-gradient(180deg, var(--accent-soft), transparent);
    font-size: 13px; display: flex; flex-direction: column; gap: 10px; animation: rise .3s ease both; }
  .approval .approval-actions { display: flex; gap: 8px; }
  .approval .approval-actions button { padding: 6px 16px; font-size: 13px; font-weight: 550; }
  .approval .approval-actions button.ok { background: var(--ok); border-color: var(--ok); color: #04130d; }
  .approval .approval-actions button.no { background: transparent; border-color: var(--danger); color: var(--danger); }
  .approval.err { border-color: var(--error-border); background: var(--error-bg); }

  /* input bar */
  #inputbar { display: flex; padding: 16px 22px 18px; border-top: 1px solid var(--border);
    background: var(--header-bg); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); }
  #inputwrap { flex: 1; max-width: 820px; margin: 0 auto; display: flex; gap: 10px; align-items: center;
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 5px 5px 5px 16px;
    transition: border-color .2s ease, box-shadow .2s ease; }
  #inputwrap:focus-within { border-color: var(--accent-line); box-shadow: 0 0 0 4px var(--accent-soft); }
  #input { flex: 1; background: transparent; border: none; color: var(--text); font-size: 14px;
    padding: 10px 0; outline: none; font-family: var(--font-ui); }
  #input::placeholder { color: var(--faint); }
  #send { background: var(--accent); border: none; color: var(--on-accent); border-radius: 10px;
    padding: 9px 17px; cursor: pointer; font-weight: 600; font-size: 13.5px;
    display: flex; align-items: center; gap: 6px; box-shadow: 0 4px 14px rgba(245,177,61,.3); }
  #send:hover { filter: brightness(1.06); }
  #send:active { transform: translateY(1px); }
  #send:disabled { opacity: .4; cursor: not-allowed; box-shadow: none; }
  #send.stopping { background: var(--danger); box-shadow: 0 4px 14px rgba(248,113,113,.3); }
  #send svg { width: 16px; height: 16px; }

  /* message hover actions */
  .msg-actions { display: flex; gap: 4px; margin-top: 6px; opacity: 0; transition: opacity .15s ease; }
  .msg:hover .msg-actions { opacity: 1; }
  .log.busy .msg-actions { opacity: 0; pointer-events: none; }
  .msg-actions button { padding: 2px 9px; font-size: 11px; border-radius: 7px; color: var(--muted);
    background: var(--panel2); border: 1px solid var(--border); }
  .msg-actions button:hover { color: var(--text); border-color: var(--accent-line); }
  .stat.flash { border: 1px dashed var(--accent-line); color: var(--accent); }

  /* edit bar */
  .editbar { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 8px 22px;
    border-top: 1px solid var(--border); background: var(--accent-soft); font-size: 12px; color: var(--accent); }
  .editbar button { padding: 2px 12px; font-size: 11.5px; color: var(--muted); }

  /* workspace manager */
  .ws-row { display: flex; align-items: center; gap: 12px; padding: 9px 12px; margin-bottom: 8px;
    border: 1px solid var(--border); border-radius: 10px; background: var(--panel2);
    transition: border-color .18s ease; }
  .ws-row:hover { border-color: var(--accent-line); }
  .ws-info { flex: 1; min-width: 0; }
  .ws-name { font-size: 13px; font-weight: 600; }
  .ws-path { font-size: 11.5px; color: var(--faint); font-family: var(--mono); word-break: break-all; }
  .ws-actions { display: flex; gap: 8px; flex: none; }
  .ws-actions button { padding: 5px 12px; font-size: 12px; }
  .ws-actions button.danger { background: transparent; border-color: var(--danger); color: var(--danger); }
  .ws-actions button:disabled { opacity: .35; cursor: not-allowed; }

  /* modal */
  .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.5); backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px); display: none; align-items: flex-start; justify-content: center;
    z-index: 50; padding: 48px 16px; }
  .modal-overlay.open { display: flex; animation: fade .25s ease; }
  @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
  .modal { background: var(--panel); border: 1px solid var(--border-strong); border-radius: 18px; width: 100%;
    max-width: 560px; padding: 24px 24px 20px; max-height: 82vh; overflow: auto; box-shadow: var(--shadow);
    animation: pop .28s cubic-bezier(.2,.8,.2,1); }
  @keyframes pop { from { opacity: 0; transform: translateY(12px) scale(.98); } to { opacity: 1; transform: none; } }
  .modal h3 { margin: 0 0 4px; font-size: 17px; font-weight: 650; display: flex; align-items: center; gap: 10px; }
  .modal h3::before { content: ""; width: 4px; height: 17px; background: var(--accent); border-radius: 2px; }
  .modal .hint { color: var(--muted); font-size: 12.5px; margin: 0 0 18px; line-height: 1.55; }
  .modal .hint code { background: var(--panel2); padding: 1px 6px; border-radius: 5px;
    font-family: var(--mono); font-size: 11.5px; border: 1px solid var(--border); }
  .modal .field { margin-bottom: 14px; }
  .modal .field label { display: block; margin-bottom: 6px; font-size: 12px; color: var(--muted); }
  .modal .row { display: flex; gap: 14px; }
  .modal .row .field { flex: 1; }
  .modal input[type=text], .modal input[type=password], .modal input[type=number] { width: 100%; }
  .modal .cb { display: flex; align-items: center; gap: 9px; margin-bottom: 11px; padding: 9px 12px;
    background: var(--panel2); border: 1px solid var(--border); border-radius: 10px; cursor: pointer;
    font-size: 12.5px; transition: border-color .18s ease; }
  .modal .cb:hover { border-color: var(--accent-line); }
  .modal .cb input { accent-color: var(--accent); width: 15px; height: 15px; }
  .modal .actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
  .modal .actions button { padding: 8px 20px; font-weight: 550; }
  .modal .actions .save { background: var(--accent); border: none; color: var(--on-accent); }
  .modal .save-note { color: var(--ok); font-size: 12px; margin-top: 10px; min-height: 14px; }

  /* settings modal: wide, flat (horizontal) layout */
  .modal.settings-modal { max-width: 1040px; width: min(1040px, 96vw); max-height: 74vh; overflow: hidden; }
  .modal.settings-modal .hint { margin-bottom: 14px; }
  .settings-shell { display: flex; gap: 0; min-height: 320px; max-height: 50vh; margin: 0 -24px;
    border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
  .settings-nav { flex: none; width: 150px; border-right: 1px solid var(--border);
    padding: 10px 8px; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
  .settings-nav .snav { text-align: left; background: transparent; border: none; color: var(--muted);
    padding: 7px 12px; border-radius: 8px; font-size: 12.5px; cursor: pointer; white-space: nowrap; }
  .settings-nav .snav:hover { background: var(--panel2); color: var(--text); }
  .settings-nav .snav.active { background: var(--accent-soft); color: var(--accent); }
  .settings-body { flex: 1; min-width: 0; padding: 14px 20px 16px; overflow-y: auto; }
  .settings-body .pane { display: none; }
  .settings-body .pane.active { display: block; animation: fade .18s ease; }
  .settings-body h4 { margin: 0 0 10px; font-size: 12px; font-weight: 650; letter-spacing: .8px;
    text-transform: uppercase; color: var(--muted); }
  .settings-body .sec { margin-bottom: 20px; }
  .set-row { display: flex; align-items: center; justify-content: space-between; gap: 14px;
    padding: 8px 0; border-bottom: 1px dashed var(--border); }
  .set-row:last-child { border-bottom: none; }
  .set-info { min-width: 0; }
  .set-label { font-size: 13px; font-weight: 550; }
  .set-desc { font-size: 11px; color: var(--faint); margin-top: 2px; line-height: 1.45; }
  .set-ctl { flex: none; display: flex; align-items: center; gap: 8px; }
  .set-ctl select { max-width: 220px; }
  .set-ctl input[type=text] { width: 220px; }
  .set-ctl .toggle { font-size: 13px; }
  .update-link { color: var(--accent); cursor: pointer; font-weight: 600; text-decoration: underline;
    text-underline-offset: 3px; }
  .icon-btn-wrap { position: relative; display: inline-flex; align-items: center; justify-content: center; }
  .icon-btn-wrap .upd-dot { position: absolute; top: 3px; right: 3px; width: 8px; height: 8px;
    border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 2px var(--panel);
    display: none; }
  .icon-btn-wrap.has-update .upd-dot { display: block; animation: fade .2s ease; }
  .kbd { font-family: var(--font-code); font-size: 11.5px; background: var(--panel2);
    border: 1px solid var(--border-strong); border-radius: 6px; padding: 2px 7px; color: var(--text); white-space: nowrap; }
  .set-list { display: flex; flex-direction: column; }
  .set-list .list-row { display: flex; align-items: center; gap: 10px; padding: 9px 12px; margin-bottom: 8px;
    border: 1px solid var(--border); border-radius: 10px; background: var(--panel2); }
  .status-dot { width: 9px; height: 9px; border-radius: 50%; flex: none;
    background: var(--danger); box-shadow: 0 0 0 3px rgba(248,113,113,.16); }
  .status-dot.on { background: var(--ok); box-shadow: 0 0 0 3px rgba(52,211,153,.16); }
  .list-row .ls-name { flex: 1; min-width: 0; font-size: 13px; font-weight: 600;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .list-row .ls-url { font-size: 11px; color: var(--faint); font-family: var(--font-code); }
  .list-row .ls-actions { display: flex; gap: 4px; flex: none; }
  .list-row .ls-actions .icon-btn { width: 30px; height: 30px; }
  .model-row { display: flex; align-items: center; gap: 10px; padding: 10px 12px; margin-bottom: 8px;
    border: 1px solid var(--border); border-radius: 10px; background: var(--panel2); }
  .model-row .m-ic { width: 30px; height: 30px; border-radius: 8px; flex: none; display: grid;
    place-items: center; background: var(--accent-soft); color: var(--accent); font-weight: 700; font-size: 13px; }
  .model-row .m-name { flex: 1; min-width: 0; font-size: 13.5px; font-weight: 650; }
  .model-row .m-status { font-size: 11px; color: var(--ok); }
  .model-row .m-status.err { color: var(--danger); }

  ::-webkit-scrollbar { width: 11px; height: 11px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 6px;
    border: 3px solid transparent; background-clip: padding-box; }
  ::-webkit-scrollbar-thumb:hover { background: var(--muted); background-clip: padding-box; }
  pre, code, .markdown pre code, .tool-card .tool-body pre,
  details.thinking .think-body pre, details.thinking .think-body code { font-family: var(--font-code); }
  .stat, .si-meta, .ops-head, .tname { font-family: var(--font-code); }
</style>
<meta name="color-scheme" content="dark light"/>
</head>
<body>
<div id="app">
<aside id="sidebar">
  <div class="side-head">
    <button class="icon-btn" id="sideToggle" onclick="toggleSidebar()" title="展开 / 收起侧边栏">
      <svg class="i-open" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg>
      <svg class="i-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></svg>
    </button>
    <span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="#1a1208"><path d="M16 5l2.6 7.2L26 15l-7.4 2.8L16 25l-2.6-7.2L6 15l7.4-2.8L16 5z"/></svg></span>
    <span class="side-brand-txt">LuminaCode</span>
  </div>
  <div class="side-section">
    <div class="side-label">工作区</div>
    <div class="side-ws">
      <select id="wsSel" onchange="switchWorkspace(this.value)" title="工作区"></select>
      <button class="icon-btn" onclick="openWsManager()" title="选择 / 管理工作区"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/></svg></button>
    </div>
  </div>
  <div class="side-section side-grow">
    <div class="side-label">会话 <span class="cnt" id="sideCnt"></span></div>
    <div id="sessionList"></div>
    <select id="sessions" style="display:none"></select>
  </div>
  <div class="side-actions">
    <button class="icon-btn" onclick="newSession()" title="新建会话"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg></button>
    <button class="icon-btn" onclick="renameSession()" title="重命名"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button>
    <button class="icon-btn" onclick="exportSession()" title="导出 Markdown"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg></button>
    <button class="icon-btn danger" onclick="deleteSession()" title="删除会话"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/></svg></button>
  </div>
  <div class="side-foot">
    <span id="tokStat" class="stat" style="display:none;"></span>
    <div class="side-foot-btns">
      <label class="toggle"><input id="autoApprove" type="checkbox"/><span>自动批准</span></label>
      <span class="foot-icns">
        <button class="icon-btn" id="themeBtn" onclick="toggleTheme()" title="切换主题">
          <svg class="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>
          <svg class="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
        </button>
        <span class="icon-btn-wrap" id="settingsBtnWrap">
          <button class="icon-btn" onclick="openSettings()" title="设置"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg><span class="upd-dot"></span></button>
        </span>
      </span>
    </div>
  </div>
</aside>
<div id="right">
<div id="work">
  <div id="main"><div id="log"></div></div>
  <aside id="toc">
    <div id="tocDots"></div>
  </aside>
  <div id="tocTip" class="toc-tip"></div>
</div>
<div id="editbar" class="editbar" style="display:none"><span>正在编辑该消息，发送后将从此处重写对话</span><button onclick="cancelEdit()">取消</button></div>
<div id="inputbar"><div id="inputwrap">
  <input id="input" placeholder="描述任务，例如：帮我修复失败的测试" autofocus/>
  <button id="send" onclick="sendBtnClick()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>发送</button>
</div></div>
</div>
</div>
<div id="settingsOverlay" class="modal-overlay" onclick="if(event.target===this)closeSettings()">
  <div class="modal settings-modal">
    <h3>设置</h3>
    <p class="hint">偏好设置自动保存到本地，重启后仍会保留。带 * 的选项仅保存，暂不生效。</p>
    <div class="settings-shell">
      <div class="settings-nav">
        <button class="snav active" data-pane="pane-desktop" onclick="switchSettingsTab(this)">桌面</button>
        <button class="snav" data-pane="pane-servers" onclick="switchSettingsTab(this)">服务器</button>
        <button class="snav" data-pane="pane-models" onclick="switchSettingsTab(this)">模型</button>
      </div>
      <div class="settings-body">
        <div class="pane active" id="pane-desktop">
          <div class="sec">
            <h4>通用</h4>
            <div class="set-row">
              <div class="set-info"><div class="set-label">语言</div><div class="set-desc">更改 LuminaCode 的显示语言 *</div></div>
              <div class="set-ctl"><select id="set_language">
                <option value="zh-CN">简体中文</option><option value="zh-TW">繁体中文</option><option value="en">English</option>
              </select></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">自动批准</div><div class="set-desc">权限请求将被自动批准</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_auto_approve" type="checkbox"/><span></span></label></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">终端 shell</div><div class="set-desc">选择终端使用的 shell。兼容的 shell 也会用于智能体工具调用 *</div></div>
              <div class="set-ctl"><select id="set_shell">
                <option value="auto">自动（默认）</option><option value="powershell">powershell</option>
                <option value="bash">bash</option><option value="cmd">cmd</option>
              </select></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">显示推理摘要</div><div class="set-desc">在时间线中显示模型推理摘要，即思考过程</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_show_reasoning" type="checkbox"/><span></span></label></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">展开 shell 工具部分</div><div class="set-desc">在时间线中展开 shell 工具部分</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_expand_shell" type="checkbox"/><span></span></label></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">展开编辑工具部分</div><div class="set-desc">在时间线中展开 write_file、edit_file 等工具部分</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_expand_edit" type="checkbox"/><span></span></label></div>
            </div>
          </div>
          <div class="sec">
            <h4>外观</h4>
            <div class="set-row">
              <div class="set-info"><div class="set-label">配色方案</div><div class="set-desc">选择跟随系统、浅色或深色主题</div></div>
              <div class="set-ctl"><select id="set_color_scheme">
                <option value="system">系统</option><option value="light">浅色</option><option value="dark">深色</option>
              </select></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">主题</div><div class="set-desc">自定义 LuminaCode 的主题 *</div></div>
              <div class="set-ctl"><select id="set_theme">
                <option value="system">system</option><option value="tokyonight">tokyonight</option>
                <option value="everforest">everforest</option><option value="ayu">ayu</option>
                <option value="catppuccin">catppuccin</option><option value="catppuccin-macchiato">catppuccin-macchiato</option>
                <option value="gruvbox">gruvbox</option><option value="kanagawa">kanagawa</option>
                <option value="nord">nord</option><option value="matrix">matrix</option><option value="one-dark">one-dark</option>
              </select></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">界面字体</div><div class="set-desc">自定义整个界面使用的字体（留空为 System Sans）</div></div>
              <div class="set-ctl"><input id="set_ui_font" type="text" placeholder="System Sans"/></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">代码字体</div><div class="set-desc">自定义代码块使用的字体（留空为 System Sans）</div></div>
              <div class="set-ctl"><input id="set_code_font" type="text" placeholder="System Sans"/></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">终端字体</div><div class="set-desc">自定义终端使用的字体（留空为 JetBrainsMono Nerd Font Mono）*</div></div>
              <div class="set-ctl"><input id="set_term_font" type="text" placeholder="JetBrainsMono Nerd Font Mono"/></div>
            </div>
          </div>
          <div class="sec">
            <h4>系统通知</h4>
            <div class="set-row">
              <div class="set-info"><div class="set-label">智能体</div><div class="set-desc">当智能体完成或需要注意时显示系统通知 *</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_notif_agent" type="checkbox"/><span></span></label></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">权限</div><div class="set-desc">当需要权限时显示系统通知 *</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_notif_permission" type="checkbox"/><span></span></label></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">错误</div><div class="set-desc">发生错误时显示系统通知 *</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_notif_error" type="checkbox"/><span></span></label></div>
            </div>
          </div>
          <div class="sec">
            <h4>音效</h4>
            <div class="set-row">
              <div class="set-info"><div class="set-label">智能体</div><div class="set-desc">当智能体完成或需要注意时播放声音 *</div></div>
              <div class="set-ctl"><select id="set_sound_agent"><option value="none">无</option></select></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">权限</div><div class="set-desc">当需要权限时播放声音 *</div></div>
              <div class="set-ctl"><select id="set_sound_permission"><option value="none">无</option></select></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">错误</div><div class="set-desc">发生错误时播放声音 *</div></div>
              <div class="set-ctl"><select id="set_sound_error"><option value="none">无</option></select></div>
            </div>
          </div>
          <div class="sec">
            <h4>更新</h4>
            <div class="set-row">
              <div class="set-info"><div class="set-label">发行说明</div><div class="set-desc">更新后显示“新功能”弹窗 *</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_release_notes" type="checkbox"/><span></span></label></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">检查更新</div><div class="set-desc">检查 GitHub 上的最新版本，发现新版本时可一键跳转下载</div></div>
              <div class="set-ctl"><button id="checkUpdateBtn" onclick="checkUpdate()">检查更新</button><span id="updateNote" class="set-desc"></span></div>
            </div>
          </div>
          <div class="sec">
            <h4>高级</h4>
            <div class="set-row">
              <div class="set-info"><div class="set-label">文件树</div><div class="set-desc">在会话中显示文件树面板 *</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_file_tree" type="checkbox"/><span></span></label></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">命令面板</div><div class="set-desc">在标题栏中显示搜索和命令面板按钮 *</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_command_palette" type="checkbox"/><span></span></label></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">服务器状态</div><div class="set-desc">在标题栏中显示服务器状态按钮 *</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_server_status" type="checkbox"/><span></span></label></div>
            </div>
            <div class="set-row">
              <div class="set-info"><div class="set-label">自定义智能体</div><div class="set-desc">在输入框中显示智能体选择器 *</div></div>
              <div class="set-ctl"><label class="toggle"><input id="set_custom_agents" type="checkbox"/><span></span></label></div>
            </div>
          </div>
          <div class="sec">
            <h4>快捷键（仅展示，暂不支持自定义）</h4>
            <div class="set-row"><div class="set-info"><div class="set-label">打开设置</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">,</span></div></div>
            <div class="set-row"><div class="set-info"><div class="set-label">返回</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">[</span></div></div>
            <div class="set-row"><div class="set-info"><div class="set-label">前进</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">]</span></div></div>
            <div class="set-row"><div class="set-info"><div class="set-label">搜索项目</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">Shift</span><span class="kbd">O</span></div></div>
            <div class="set-row"><div class="set-info"><div class="set-label">新建会话</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">T</span></div></div>
            <div class="set-row"><div class="set-info"><div class="set-label">关闭终端</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">W</span></div></div>
            <div class="set-row"><div class="set-info"><div class="set-label">切换终端</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">`</span></div></div>
            <div class="set-row"><div class="set-info"><div class="set-label">新建终端</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">Alt</span><span class="kbd">T</span></div></div>
            <div class="set-row"><div class="set-info"><div class="set-label">Prompt</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">Shift</span><span class="kbd">E</span></div></div>
            <div class="set-row"><div class="set-info"><div class="set-label">Shell</div></div><div class="set-ctl"><span class="kbd">Ctrl</span><span class="kbd">Shift</span><span class="kbd">X</span></div></div>
          </div>
        </div>
        <div class="pane" id="pane-servers">
          <div class="sec">
            <h4>服务器列表</h4>
            <p class="hint" style="margin-bottom:12px">连接远程 LuminaCode 服务器。*：当前仅保存配置，尚未实现远程连接。</p>
            <div class="set-ctl" style="justify-content:flex-end; margin-bottom:12px">
              <button onclick="openServerDialog(-1)">添加服务器</button>
            </div>
            <div class="set-list" id="serverList"></div>
          </div>
        </div>
        <div class="pane" id="pane-models">
          <div class="sec">
            <h4>模型列表</h4>
            <p class="hint" style="margin-bottom:12px">DeepSeek V4 Flash 是当前默认模型。初次使用请点击 ··· 配置 API Key。</p>
            <div class="set-list" id="modelList"></div>
          </div>
        </div>
      </div>
    </div>
    <div class="actions">
      <button class="save" onclick="closeSettings()">关闭</button>
    </div>
    <div id="saveNote" class="save-note"></div>
  </div>
</div>
<div id="serverOverlay" class="modal-overlay" onclick="if(event.target===this)closeServerDialog()">
  <div class="modal" style="max-width:460px">
    <h3 id="serverDialogTitle">添加服务器</h3>
    <p class="hint">填写要连接的服务器的信息。密码会被保存到本地状态文件。</p>
    <div class="field"><label>服务器 URL</label><input id="srv_url" type="text" placeholder="http://localhost:1200"/></div>
    <div class="field"><label>服务器名称（可选）</label><input id="srv_name" type="text" placeholder="Localhost"/></div>
    <div class="row">
      <div class="field"><label>用户名（可选）</label><input id="srv_user" type="text" value="lumina-code"/></div>
      <div class="field"><label>密码（可选）</label><input id="srv_password" type="password" placeholder="密码"/></div>
    </div>
    <div class="actions">
      <button onclick="closeServerDialog()">取消</button>
      <button class="save" onclick="saveServerDialog()">保存</button>
    </div>
    <div id="srvNote" class="save-note"></div>
  </div>
</div>
<div id="modelOverlay" class="modal-overlay" onclick="if(event.target===this)closeModelDialog()">
  <div class="modal">
    <h3>配置 DeepSeek V4 Flash</h3>
    <p class="hint">修改将写入工作区 <code>.env</code> 文件。保存后新会话生效；运行中的任务不受影响。</p>
    <div class="field"><label>API Key</label><input id="cfg_DEEPSEEK_API_KEY" type="password" autocomplete="off"/></div>
    <details style="margin-bottom:12px;border:1px solid var(--border);border-radius:10px;padding:10px 14px">
      <summary style="cursor:pointer;font-size:12.5px;color:var(--muted)">高级参数</summary>
      <div style="margin-top:12px">
        <div class="field"><label>Base URL</label><input id="cfg_DEEPSEEK_BASE_URL" type="text"/></div>
        <div class="row">
          <div class="field"><label>模型 (DEEPSEEK_MODEL)</label><input id="cfg_DEEPSEEK_MODEL" type="text"/></div>
          <div class="field"><label>规划模型 (DEEPSEEK_PLANNER_MODEL)</label><input id="cfg_DEEPSEEK_PLANNER_MODEL" type="text"/></div>
        </div>
        <div class="row">
          <div class="field"><label>单次请求输出上限 (LUMINA_MAX_TOKENS ≤8192)</label><input id="cfg_LUMINA_MAX_TOKENS" type="number"/></div>
          <div class="field"><label>任务累计预算 (LUMINA_TOKEN_BUDGET)</label><input id="cfg_LUMINA_TOKEN_BUDGET" type="number"/></div>
        </div>
        <div class="row">
          <div class="field"><label>最大迭代 (LUMINA_MAX_ITERATIONS)</label><input id="cfg_LUMINA_MAX_ITERATIONS" type="number"/></div>
          <div class="field"><label>温度 (LUMINA_TEMPERATURE)</label><input id="cfg_LUMINA_TEMPERATURE" type="number" step="0.1"/></div>
        </div>
        <label class="cb"><input id="cfg_LUMINA_ENABLE_PLANNER" type="checkbox"/>启用 Reasoner 规划 (LUMINA_ENABLE_PLANNER)</label>
        <label class="cb"><input id="cfg_LUMINA_COMPRESSION" type="checkbox"/>上下文压缩 (LUMINA_COMPRESSION)</label>
        <label class="cb"><input id="cfg_LUMINA_SELF_REVIEW" type="checkbox"/>完成时自我审查 (LUMINA_SELF_REVIEW)</label>
      </div>
    </details>
    <div class="actions">
      <button onclick="closeModelDialog()">取消</button>
      <button class="save" onclick="saveModelConfig()">保存</button>
    </div>
    <div id="modelNote" class="save-note"></div>
  </div>
</div>
<div id="wsOverlay" class="modal-overlay" onclick="if(event.target===this)closeWsManager()">
  <div class="modal">
    <h3>选择工作区</h3>
    <p class="hint">切换要使用的项目目录。添加的工作区会保存到 <code>LUMINA_WORKSPACES</code>，下次启动仍可选用。</p>
    <div id="wsList"></div>
    <div class="field">
      <label>添加工作区</label>
      <div class="row">
        <input id="wsPathInput" type="text" placeholder="输入项目目录的绝对路径"/>
        <button onclick="browseWsFolder()" style="flex:none" title="选择文件夹">浏览…</button>
      </div>
    </div>
    <div class="actions">
      <button onclick="closeWsManager()">关闭</button>
      <button class="save" onclick="addWs()">添加</button>
    </div>
    <div id="wsNote" class="save-note"></div>
  </div>
</div>
<script>
let ws = null;
let activeWorkspace = "";
const log = document.getElementById("log");
const main = document.getElementById("main");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
let busy = false;
let currentSession = null;
let sessionsData = [];
let userCounter = 0;
let editingUi = null;
let streamEl = null, mdBuf = "";
let thinkingEl = null, thinkBuf = "";
let thinkStart = 0, thinkTimer = null, thinkSpan = null;
let opsCard = null, opsHead = null, opsBody = null, opsPending = null;
let opsReads = new Set(), opsSkills = 0, opsEdits = {};
let inputHistory = [];
let histIndex = -1;
let tokenUsed = 0;

function connectWS(path){
  if (ws) { ws.onclose = null; ws.close(); }
  activeWorkspace = path || "";
  ws = new WebSocket(`ws://${location.host}/ws${activeWorkspace ? "?w=" + encodeURIComponent(activeWorkspace) : ""}`);
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "list" }));
    if (settings && settings.auto_approve) ws.send(JSON.stringify({ type: "set_auto", value: true }));
  };
  ws.onmessage = (e) => handleWSMessage(JSON.parse(e.data));
}

function setBusy(b){
  busy = b;
  log.classList.toggle("busy", b);
  if (b) {
    sendBtn.dataset.mode = "stop";
    sendBtn.classList.add("stopping");
    sendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>停止';
  } else {
    sendBtn.dataset.mode = "send";
    sendBtn.classList.remove("stopping");
    sendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>发送';
  }
}
function sendBtnClick(){
  if (busy) stopRun();
  else send();
}
function updateTok(){
  const el = document.getElementById("tokStat");
  if (tokenUsed > 0) { el.textContent = "tokens: " + tokenUsed; el.style.display = "inline"; }
  else el.style.display = "none";
}

function scrollBottom(){ main.scrollTop = main.scrollHeight; }

/* ---------- markdown (minimal, safe) ---------- */
function esc(s){ return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function parseTableRow(line){
  let parts = line.trim().split("|");
  if (parts.length && parts[0].trim() === "") parts.shift();
  if (parts.length && parts[parts.length - 1].trim() === "") parts.pop();
  return parts.map(c => c.trim());
}
function isTableSep(line){
  const cells = parseTableRow(line);
  return cells.length > 0 && cells.every(c => /^:?-+:?$/.test(c));
}
function renderMarkdown(src){
  let s = esc(String(src || "").replace(/\\r\\n/g, "\\n"));
  const stash = [];
  const key = () => "\\u0000" + stash.length + "\\u0000";
  s = s.replace(/```([\\w+-]*)\\n([\\s\\S]*?)```/g, (m, lang, code) => { const k = key(); stash.push("<pre><code>"+code+"</code></pre>"); return k; });
  s = s.replace(/`([^`\\n]+)`/g, (m, c) => { const k = key(); stash.push("<code>"+c+"</code>"); return k; });
  s = s.replace(/\\*\\*([^*]+)\\*\\*/g, (m, t) => "<strong>"+t+"</strong>");
  s = s.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)\\s]+)\\)/g, (m, t, u) => '<a href="'+u+'" target="_blank" rel="noopener noreferrer">'+t+"</a>");
  const lines = s.split("\\n");
  let out = "";
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const h = line.match(/^(#{1,3})\\s+(.*)$/);
    if (h) { out += "<h"+h[1].length+">"+h[2]+"</h"+h[1].length+">"; i++; continue; }
    if (/^\\u0000\\d+\\u0000$/.test(line.trim())) { out += stash[+line.trim().replace(/\\u0000/g,"")] || ""; i++; continue; }
    if (/^&gt; /.test(line)) { const q=[]; while (i<lines.length && /^&gt; /.test(lines[i])) { q.push(lines[i].replace(/^&gt; /,"")); i++; } out += "<blockquote>"+q.join("<br>")+"</blockquote>"; continue; }
    if (/^\\s*(?:-{3,}|\\*{3,}|_{3,})\\s*$/.test(line)) { out += "<hr/>"; i++; continue; }
    if (/^[-*] /.test(line)) { const it=[]; while (i<lines.length && /^[-*] /.test(lines[i])) { it.push(lines[i].replace(/^[-*] /,"")); i++; } out += "<ul>"+it.map(x=>"<li>"+x+"</li>").join("")+"</ul>"; continue; }
    if (/^\\d+\\. /.test(line)) { const it=[]; while (i<lines.length && /^\\d+\\. /.test(lines[i])) { it.push(lines[i].replace(/^\\d+\\. /,"")); i++; } out += "<ol>"+it.map(x=>"<li>"+x+"</li>").join("")+"</ol>"; continue; }
    if (line.indexOf("|") !== -1 && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const rows = [parseTableRow(line)];
      let j = i + 2;
      while (j < lines.length && lines[j].indexOf("|") !== -1 && !isTableSep(lines[j])) {
        rows.push(parseTableRow(lines[j])); j++;
      }
      const head = rows[0];
      let t = "<table><thead><tr>" + head.map(h => "<th>" + (h || "") + "</th>").join("") + "</tr></thead><tbody>";
      for (let r = 1; r < rows.length; r++) {
        t += "<tr>" + rows[r].map(c => "<td>" + (c || "") + "</td>").join("") + "</tr>";
      }
      t += "</tbody></table>";
      out += t;
      i = j;
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() !== "") { para.push(lines[i]); i++; }
    if (para.length) out += "<p>"+para.join("<br>")+"</p>";
    i++;
  }
  out = out.replace(/\\u0000(\\d+)\\u0000/g, (m, n) => stash[+n] || "");
  return out;
}

/* ---------- DOM helpers ---------- */
function appendMd(cls, text){
  const div = document.createElement("div");
  div.className = "msg " + cls;
  if (cls === "user") { div.dataset.uindex = userCounter++; div.dataset.text = text; }
  else if (cls === "assistant") div.dataset.text = text;
  const inner = document.createElement("div");
  inner.className = "bubble markdown";
  inner.innerHTML = renderMarkdown(text);
  div.appendChild(inner);
  if (cls === "user" || cls === "assistant") div.appendChild(buildMsgActions(div, cls));
  log.appendChild(div);
  scrollBottom();
  if (cls === "user") rebuildToc();
  return inner;
}
/* ---------- message actions: copy / edit / resend / regenerate ---------- */
function actionBtn(label, fn){
  const b = document.createElement("button");
  b.textContent = label;
  b.onclick = fn;
  return b;
}
function buildMsgActions(div, cls){
  const box = document.createElement("div");
  box.className = "msg-actions";
  box.appendChild(actionBtn("复制", () => copyMessage(div)));
  if (cls === "user") {
    box.appendChild(actionBtn("编辑", () => editMessage(div)));
    box.appendChild(actionBtn("重新发送", () => resendMessage(div)));
  } else {
    box.appendChild(actionBtn("重新生成", () => regenerateAt(div)));
  }
  return box;
}
function flashNote(text){
  const div = document.createElement("div");
  div.className = "stat flash";
  div.textContent = text;
  log.appendChild(div);
  scrollBottom();
  setTimeout(() => div.remove(), 1600);
}
function legacyCopy(text, done){
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); done(); } catch (e) {}
  document.body.removeChild(ta);
}
function copyMessage(el){
  const text = el.dataset.text || "";
  if (!text) return;
  const done = () => flashNote("[copied] 已复制");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => legacyCopy(text, done));
  } else legacyCopy(text, done);
}
function showEditbar(){ document.getElementById("editbar").style.display = "flex"; }
function hideEditbar(){ const el = document.getElementById("editbar"); if (el) el.style.display = "none"; }
function cancelEdit(){ editingUi = null; hideEditbar(); }
function editMessage(el){
  editingUi = parseInt(el.dataset.uindex, 10);
  input.value = el.dataset.text || "";
  input.focus();
  showEditbar();
}
function resendMessage(el){
  truncateAndSend(parseInt(el.dataset.uindex, 10), el.dataset.text || "");
}
function regenerateAt(el){
  let prev = el.previousElementSibling;
  while (prev && !(prev.classList.contains("msg") && prev.classList.contains("user"))) {
    prev = prev.previousElementSibling;
  }
  if (prev) truncateAndSend(parseInt(prev.dataset.uindex, 10), prev.dataset.text || "");
}
function truncateAndSend(ui, text){
  if (busy || !currentSession || ui < 0) return;
  const target = document.querySelector('.msg.user[data-uindex="' + ui + '"]');
  while (target && target.nextSibling) log.removeChild(target.nextSibling);
  if (target) target.remove();
  hideEditbar();
  editingUi = null;
  userCounter = ui;
  ws.send(JSON.stringify({ type: "truncate", session_id: currentSession, before_user: ui }));
  setBusy(true);
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
  appendMd("user", text);
  ws.send(JSON.stringify({ type: "message", content: text }));
}
/* ---------- right conversation navigation (floating dots) ---------- */
let tocDots = [];
function rebuildToc(){
  const wrap = document.getElementById("tocDots");
  if (!wrap) return;
  wrap.innerHTML = "";
  tocDots = [];
  document.querySelectorAll(".msg.user[data-uindex]").forEach(el => {
    const n = parseInt(el.dataset.uindex, 10);
    const dot = document.createElement("div");
    dot.className = "toc-dot";
    dot.dataset.uindex = n;
    dot.onclick = () => el.scrollIntoView({ behavior: "smooth", block: "center" });
    dot.onmouseenter = () => showTocTip(dot, el);
    dot.onmouseleave = hideTocTip;
    wrap.appendChild(dot);
    tocDots.push({ dot, msg: el, idx: n });
  });
  tocFocus = 0;
  clearTimeout(tocWheelTimer);
  tocWheelTimer = null;
  updateTocActive();
}
let tocFocus = 0;
let tocWheelTimer = null;
function layoutToc(activePos){
  const wrap = document.getElementById("tocDots");
  if (!wrap || !tocDots.length) return;
  const H = wrap.clientHeight;
  const centerY = H / 2;
  tocDots.forEach((it, i) => {
    const d = i - tocFocus;
    const dist = Math.abs(d);
    const size = Math.max(5, 13 - dist * 1.6);
    const opacity = Math.max(0.15, 1 - dist * 0.17);
    it.dot.style.top = (centerY + d * 24) + "px";
    it.dot.style.width = size + "px";
    it.dot.style.height = size + "px";
    it.dot.style.opacity = opacity.toFixed(2);
    it.dot.classList.toggle("active", i === activePos);
  });
}
function updateTocActive(){
  if (!tocDots.length) return;
  const mTop = main.getBoundingClientRect().top;
  let cur = null;
  document.querySelectorAll(".msg.user[data-uindex]").forEach(el => {
    if (el.getBoundingClientRect().top - mTop - 120 <= 0) cur = el;
  });
  let activePos = 0;
  if (cur) {
    const curIdx = parseInt(cur.dataset.uindex, 10);
    for (let i = 0; i < tocDots.length; i++) {
      if (tocDots[i].idx === curIdx) { activePos = i; break; }
    }
  }
  if (!tocWheelTimer) tocFocus = activePos;
  layoutToc(activePos);
}
function showTocTip(dot, el){
  const tip = document.getElementById("tocTip");
  if (!tip) return;
  tip.innerHTML = "";
  const t = document.createElement("div");
  t.className = "toc-tip-title";
  t.textContent = "对话 " + (parseInt(el.dataset.uindex, 10) + 1);
  const b = document.createElement("div");
  b.className = "toc-tip-body";
  b.textContent = el.dataset.text || "";
  tip.appendChild(t); tip.appendChild(b);
  tip.style.opacity = "1";
  const r = dot.getBoundingClientRect();
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  let x = r.left - tw - 12;
  let y = r.top + r.height / 2 - th / 2;
  if (x < 8) x = r.right + 12;
  y = Math.max(8, Math.min(y, window.innerHeight - th - 8));
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
function hideTocTip(){
  const tip = document.getElementById("tocTip");
  if (tip) tip.style.opacity = "0";
}
main.addEventListener("scroll", updateTocActive);
window.addEventListener("resize", updateTocActive);
(function initTocWheel(){
  const wrap = document.getElementById("tocDots");
  if (!wrap) return;
  wrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    main.scrollTop += e.deltaY;
    clearTimeout(tocWheelTimer);
    tocWheelTimer = setTimeout(() => { tocWheelTimer = null; updateTocActive(); }, 1600);
    const dir = e.deltaY > 0 ? 1 : -1;
    tocFocus = Math.max(0, Math.min(tocDots.length - 1, tocFocus + dir));
    updateTocActive();
  }, { passive: false });
})();
function appendStat(text){
  const div = document.createElement("div");
  div.className = "msg stat";
  div.textContent = text;
  log.appendChild(div);
  scrollBottom();
  return div;
}
/* ---------- tool ops summary card ---------- */
function resetOps(){
  opsCard = null; opsHead = null; opsBody = null; opsPending = null;
  opsReads = new Set(); opsSkills = 0; opsEdits = {};
}
function ensureOpsCard(){
  if (opsCard) return;
  const card = document.createElement("div");
  card.className = "tool-card";
  const head = document.createElement("div");
  head.className = "tool-head";
  const dot = document.createElement("span"); dot.className = "dot";
  opsHead = document.createElement("span"); opsHead.className = "ops-head";
  opsHead.style.whiteSpace = "pre-line";
  const chev = document.createElement("span"); chev.className = "chev"; chev.textContent = "▸";
  head.appendChild(dot); head.appendChild(opsHead); head.appendChild(chev);
  opsBody = document.createElement("div");
  opsBody.className = "tool-body";
  head.onclick = () => {
    const open = opsBody.style.display !== "none";
    opsBody.style.display = open ? "none" : "block";
    card.classList.toggle("open", !open);
    chev.textContent = open ? "▸" : "▾";
  };
  card.appendChild(head); card.appendChild(opsBody);
  if (settings.expand_shell || settings.expand_edit) {
    opsBody.style.display = "block";
    card.classList.add("open");
    chev.textContent = "▾";
  }
  log.appendChild(card);
  opsCard = card;
  scrollBottom();
}
function renderOpsHead(){
  if (!opsCard) return;
  const parts = [];
  if (opsReads.size) parts.push("已读取 " + opsReads.size + " 个文件");
  if (opsSkills) parts.push("调用 " + opsSkills + " 个技能");
  const paths = Object.keys(opsEdits);
  let text = parts.join(" · ");
  if (paths.length) {
    const lines = paths.map(p => "已编辑 " + p + " +" + opsEdits[p].added + " -" + opsEdits[p].removed);
    if (text) text += "\\n";
    text += lines.join("\\n");
  }
  opsHead.textContent = text || "工具操作";
}
function appendOpsDetail(name, args){
  const pre = document.createElement("pre");
  const argText = JSON.stringify(args || {});
  pre.textContent = "$ " + name + " " + (argText.length > 80 ? argText.slice(0, 80) + "…" : argText);
  opsBody.appendChild(pre);
  return pre;
}
function resetStream(){ streamEl = null; mdBuf = ""; }
function finalizeStreamText(){
  if (streamEl && streamEl.parentElement) streamEl.parentElement.dataset.text = mdBuf;
}

/* ---------- thinking timer ---------- */
function updateThinkLabel(){
  if (thinkSpan) thinkSpan.textContent = "已思考 " + Math.max(0, Math.round((Date.now() - thinkStart) / 1000)) + " 秒";
}
function startThinkTimer(){
  thinkStart = Date.now();
  clearInterval(thinkTimer);
  thinkTimer = setInterval(updateThinkLabel, 1000);
  updateThinkLabel();
}
function stopThinkTimer(){
  clearInterval(thinkTimer);
  thinkTimer = null;
  updateThinkLabel();
}

/* ---------- websocket ---------- */
function handleWSMessage(m) {
  if (m.type === "sessions") renderSessions(m.sessions);
  else if (m.type === "session") { currentSession = m.session.id; tokenUsed = 0; updateTok(); }
  else if (m.type === "session_cleared") { currentSession = null; tokenUsed = 0; updateTok(); log.innerHTML = ""; userCounter = 0; editingUi = null; hideEditbar(); rebuildToc(); }
  else if (m.type === "history") {
    userCounter = 0;
    m.messages.forEach(msg => {
      if (msg.role === "user") appendMd("user", msg.content);
      else if (msg.role === "assistant") appendMd("assistant", msg.content);
    });
  } else if (m.type === "reasoning") {
    if (!settings.show_reasoning) return;
    if (!thinkingEl) {
      const det = document.createElement("details");
      det.className = "thinking";
      det.open = false;
      const sum = document.createElement("summary");
      sum.innerHTML = '<svg class="think-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9L12 3Z"/><path d="M19 14l.7 1.8L21.5 16.5l-1.8.7L19 19l-.7-1.8L16.5 16.5l1.8-.7L19 14Z"/></svg><span>已思考 0 秒</span>';
      const tb = document.createElement("div");
      tb.className = "think-body";
      det.appendChild(sum); det.appendChild(tb);
      log.appendChild(det);
      thinkingEl = tb;
      thinkBuf = "";
      thinkSpan = sum.querySelector("span");
      startThinkTimer();
    }
    thinkBuf += m.chunk;
    thinkingEl.innerHTML = renderMarkdown(thinkBuf);
    scrollBottom();
  } else if (m.type === "stream") {
    if (!streamEl) {
      stopThinkTimer();
      const div = document.createElement("div");
      div.className = "msg assistant";
      div.dataset.text = "";
      const inner = document.createElement("div");
      inner.className = "bubble markdown";
      div.appendChild(inner);
      div.appendChild(buildMsgActions(div, "assistant"));
      log.appendChild(div);
      streamEl = inner;
      mdBuf = "";
    }
    mdBuf += m.chunk;
    streamEl.innerHTML = renderMarkdown(mdBuf);
    scrollBottom();
  } else if (m.type === "tool_call") {
    resetStream();
    stopThinkTimer();
    ensureOpsCard();
    const name = m.name || "";
    const args = m.arguments || {};
    if (name === "read_file" && args.path) opsReads.add(args.path);
    else if (name === "write_file" || name === "edit_file" || name === "replace_all") { /* counted on result */ }
    else opsSkills++;
    renderOpsHead();
    opsPending = appendOpsDetail(name, args);
  } else if (m.type === "tool_result") {
    if (!opsCard) ensureOpsCard();
    if (m.stats && m.stats.path) {
      const p = m.stats.path;
      if (!opsEdits[p]) opsEdits[p] = { added: 0, removed: 0 };
      opsEdits[p].added += m.stats.added || 0;
      opsEdits[p].removed += m.stats.removed || 0;
      renderOpsHead();
    }
    if (opsPending) {
      if (m.is_error) opsPending.classList.add("err");
      const line = document.createElement("pre");
      line.textContent = "\\n[" + (m.is_error ? "error" : "ok") + "]\\n" + (m.content || "");
      opsPending.appendChild(line);
      opsPending = null;
    }
    scrollBottom();
  } else if (m.type === "approval_request") {
    if (document.getElementById("autoApprove").checked) { respond(m.request_id, true); return; }
    const box = document.createElement("div");
    box.className = "approval";
    box.textContent = "需要批准: " + m.name + " (" + m.reason + ")";
    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const yes = document.createElement("button");
    yes.className = "ok"; yes.textContent = "批准";
    yes.onclick = () => { box.textContent = "[已批准] " + m.name; respond(m.request_id, true); };
    const no = document.createElement("button");
    no.className = "no"; no.textContent = "拒绝";
    no.onclick = () => { box.textContent = "[已拒绝] " + m.name; box.classList.add("err"); respond(m.request_id, false); };
    actions.appendChild(yes); actions.appendChild(no);
    box.appendChild(actions);
    log.appendChild(box);
    scrollBottom();
  } else if (m.type === "done") {
    stopThinkTimer();
    finalizeStreamText();
    resetStream();
    setBusy(false);
    tokenUsed += m.total_tokens || 0;
    updateTok();
    let hint = "";
    if (m.stopped_reason === "budget_exhausted") hint = " （已达累计 token 预算，可在 .env 调大 LUMINA_TOKEN_BUDGET）";
    appendStat("[done] iter=" + m.iterations + " tools=" + m.tool_calls + " tokens=" + m.total_tokens + " stop=" + m.stopped_reason + hint);
  } else if (m.type === "cancelled") {
    stopThinkTimer(); finalizeStreamText(); resetStream(); setBusy(false);
    appendStat("[stopped] 任务已手动停止");
  } else if (m.type === "error") {
    stopThinkTimer(); finalizeStreamText(); resetStream(); setBusy(false);
    appendMd("error", "错误: " + m.message);
  }
}

function switchWorkspace(value){
  if (busy) return;
  currentSession = null;
  log.innerHTML = "";
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
  userCounter = 0; editingUi = null; hideEditbar();
  rebuildToc();
  tokenUsed = 0; updateTok();
  connectWS(value);
  persistDefaultWorkspace(value);
}

function renderSessions(sessions) {
  sessionsData = sessions || [];
  document.getElementById("sideCnt").textContent = sessionsData.length ? "· " + sessionsData.length : "";
  const list = document.getElementById("sessionList");
  list.innerHTML = "";
  sessionsData.forEach(s => {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === currentSession ? " active" : "");
    item.onclick = () => switchSession(s.id);
    const dot = document.createElement("span"); dot.className = "si-dot";
    const title = document.createElement("span"); title.className = "si-title";
    title.textContent = (s.title || "#" + s.id).slice(0, 26);
    title.title = s.title || "";
    const meta = document.createElement("span"); meta.className = "si-meta";
    meta.textContent = "#" + s.id + " · " + s.messages;
    item.appendChild(dot); item.appendChild(title); item.appendChild(meta);
    list.appendChild(item);
  });
}
function respond(id, approved) {
  ws.send(JSON.stringify({ type: "approval_response", request_id: id, approved }));
}
function switchSession(id) {
  if (busy || !id) return;
  log.innerHTML = "";
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
  userCounter = 0; editingUi = null; hideEditbar();
  rebuildToc();
  tokenUsed = 0; updateTok();
  ws.send(JSON.stringify({ type: "resume", session_id: Number(id) }));
}
function newSession() {
  if (busy) return;
  editingUi = null; hideEditbar();
  ws.send(JSON.stringify({ type: "new_session" }));
}
function renameSession() {
  if (busy || !currentSession) return;
  const cur = (sessionsData.find(s => s.id === currentSession) || {}).title || "";
  const t = prompt("新的会话标题", cur);
  if (t === null) return;
  ws.send(JSON.stringify({ type: "rename_session", session_id: currentSession, title: t }));
}
function stopRun() {
  ws.send(JSON.stringify({ type: "cancel" }));
}
function deleteSession() {
  if (busy || !currentSession) return;
  if (!confirm("确定删除会话 #" + currentSession + " 吗？该操作不可恢复。")) return;
  ws.send(JSON.stringify({ type: "delete_session", session_id: currentSession }));
}
function send() {
  const text = input.value.trim();
  if (!text || busy) return;
  if (editingUi != null) { const ui = editingUi; editingUi = null; hideEditbar(); truncateAndSend(ui, text); return; }
  inputHistory.push(text); if (inputHistory.length > 100) inputHistory.shift();
  histIndex = inputHistory.length;
  setBusy(true);
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
  appendMd("user", text);
  ws.send(JSON.stringify({ type: "message", content: text }));
  input.value = "";
}
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") send();
  else if (e.key === "ArrowUp") { if (inputHistory.length && histIndex > 0) { histIndex--; input.value = inputHistory[histIndex]; } }
  else if (e.key === "ArrowDown") { if (histIndex < inputHistory.length) { histIndex++; input.value = histIndex < inputHistory.length ? inputHistory[histIndex] : ""; } }
});
document.getElementById("autoApprove").addEventListener("change", (e) => {
  ws.send(JSON.stringify({ type: "set_auto", value: e.target.checked }));
  settings.auto_approve = e.target.checked;
  persistSettings();
});

/* ---------- theme ---------- */
let settings = {};
let settingsReady = false;
const APP_VERSION = "1.0.2";
const THEMES = ["system","tokyonight","everforest","ayu","catppuccin","catppuccin-macchiato","gruvbox","kanagawa","nord","matrix","one-dark"];
(function initThemeFast(){
  document.documentElement.setAttribute("data-theme", localStorage.getItem("lumina-theme") || "dark");
})();
function updateThemeBtn(){ /* theme icon toggled via CSS based on [data-theme] */ }
updateThemeBtn();
function applyTheme(){
  const scheme = settings.color_scheme || "system";
  const dark = scheme === "dark" || (scheme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  try { localStorage.setItem("lumina-theme", dark ? "dark" : "light"); } catch (e) {}
  if (settings.theme === "matrix") document.documentElement.setAttribute("data-theme-style", "matrix");
  else document.documentElement.removeAttribute("data-theme-style");
  updateThemeBtn();
}
function toggleTheme(){
  const darkNow = document.documentElement.getAttribute("data-theme") === "dark";
  settings.color_scheme = darkNow ? "light" : "dark";
  applyTheme();
  persistSettings();
}
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!settings.color_scheme || settings.color_scheme === "system") applyTheme();
});

/* ---------- sidebar ---------- */
function toggleSidebar(){
  const sb = document.getElementById("sidebar");
  const collapsed = sb.classList.toggle("collapsed");
  document.body.classList.toggle("sidebar-hidden", collapsed);
  try { localStorage.setItem("lumina-sidebar", collapsed ? "1" : "0"); } catch (e) {}
}
(function initSidebar(){
  const sb = document.getElementById("sidebar");
  if (sb && localStorage.getItem("lumina-sidebar") === "1") {
    sb.classList.add("collapsed");
    document.body.classList.add("sidebar-hidden");
  }
})();

/* ---------- settings panel ---------- */
function setCssVar(name, value, fallback){
  if (value) document.documentElement.style.setProperty(name, value + ", " + fallback);
  else document.documentElement.style.removeProperty(name);
}
function applyFonts(){
  setCssVar("--font-ui", settings.ui_font || "", "var(--sans)");
  setCssVar("--font-code", settings.code_font || "", "var(--mono)");
  setCssVar("--font-term", settings.term_font || "", "var(--mono)");
}
function applySettings(){
  applyTheme();
  applyFonts();
  const aa = document.getElementById("autoApprove");
  if (aa) aa.checked = !!settings.auto_approve;
}
function readSettingsFromDom(){
  const map = {
    language: document.getElementById("set_language").value,
    auto_approve: document.getElementById("set_auto_approve").checked,
    shell: document.getElementById("set_shell").value,
    show_reasoning: document.getElementById("set_show_reasoning").checked,
    expand_shell: document.getElementById("set_expand_shell").checked,
    expand_edit: document.getElementById("set_expand_edit").checked,
    color_scheme: document.getElementById("set_color_scheme").value,
    theme: document.getElementById("set_theme").value,
    ui_font: document.getElementById("set_ui_font").value.trim(),
    code_font: document.getElementById("set_code_font").value.trim(),
    term_font: document.getElementById("set_term_font").value.trim(),
    notif_agent: document.getElementById("set_notif_agent").checked,
    notif_permission: document.getElementById("set_notif_permission").checked,
    notif_error: document.getElementById("set_notif_error").checked,
    sound_agent: document.getElementById("set_sound_agent").value,
    sound_permission: document.getElementById("set_sound_permission").value,
    sound_error: document.getElementById("set_sound_error").value,
    release_notes: document.getElementById("set_release_notes").checked,
    file_tree: document.getElementById("set_file_tree").checked,
    command_palette: document.getElementById("set_command_palette").checked,
    server_status: document.getElementById("set_server_status").checked,
    custom_agents: document.getElementById("set_custom_agents").checked,
  };
  settings = Object.assign({}, settings, map);
}
function writeSettingsToDom(){
  const ids = {
    language: "set_language", auto_approve: "set_auto_approve", shell: "set_shell",
    show_reasoning: "set_show_reasoning", expand_shell: "set_expand_shell", expand_edit: "set_expand_edit",
    color_scheme: "set_color_scheme", theme: "set_theme", ui_font: "set_ui_font",
    code_font: "set_code_font", term_font: "set_term_font", notif_agent: "set_notif_agent",
    notif_permission: "set_notif_permission", notif_error: "set_notif_error",
    sound_agent: "set_sound_agent", sound_permission: "set_sound_permission", sound_error: "set_sound_error",
    release_notes: "set_release_notes", file_tree: "set_file_tree", command_palette: "set_command_palette",
    server_status: "set_server_status", custom_agents: "set_custom_agents",
  };
  Object.keys(ids).forEach(key => {
    const el = document.getElementById(ids[key]);
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!settings[key];
    else el.value = settings[key] == null ? "" : settings[key];
  });
}
function persistSettings(){
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  }).then(r => r.json()).then(res => {
    const note = document.getElementById("saveNote");
    if (note) note.textContent = res.ok ? "已保存" : ("保存失败: " + (res.message || ""));
  }).catch(() => {});
}
function settingsChanged(){
  if (!settingsReady) return;
  readSettingsFromDom();
  applySettings();
  persistSettings();
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "set_auto", value: !!settings.auto_approve }));
}
function switchSettingsTab(btn){
  document.querySelectorAll(".settings-nav .snav").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".settings-body .pane").forEach(p => p.classList.remove("active"));
  document.getElementById(btn.dataset.pane).classList.add("active");
  if (btn.dataset.pane === "pane-servers") renderServers();
  if (btn.dataset.pane === "pane-models") renderModels();
}
function loadSettings(){
  return fetch("/api/settings").then(r => r.json()).then(data => {
    settings = data || {};
    writeSettingsToDom();
    applySettings();
    renderModels();
    settingsReady = true;
  }).catch(() => { settingsReady = true; });
}
function openSettings(){
  document.getElementById("saveNote").textContent = "";
  loadSettings();
  document.getElementById("settingsOverlay").classList.add("open");
}
function closeSettings(){ document.getElementById("settingsOverlay").classList.remove("open"); }
(function bindSettingsControls(){
  document.querySelectorAll("#settingsOverlay .set-ctl input, #settingsOverlay .set-ctl select").forEach(el => {
    el.addEventListener("change", settingsChanged);
  });
})();

/* ---------- servers ---------- */
let servers = [];
let serverEditing = -1;
function loadServers(){
  return fetch("/api/servers").then(r => r.json()).then(data => {
    servers = (data && data.servers) || [];
    renderServers();
  }).catch(() => {});
}
function renderServers(){
  const box = document.getElementById("serverList");
  box.innerHTML = "";
  if (!servers.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "尚未添加服务器。点击右上角“添加服务器”进行添加。";
    box.appendChild(p);
    return;
  }
  servers.forEach((s, i) => {
    const row = document.createElement("div");
    row.className = "list-row";
    const dot = document.createElement("span");
    dot.className = "status-dot";
    const info = document.createElement("div");
    info.style.minWidth = "0";
    const name = document.createElement("div");
    name.className = "ls-name";
    name.textContent = s.name || s.url;
    const url = document.createElement("div");
    url.className = "ls-url";
    url.textContent = s.url;
    info.appendChild(name); info.appendChild(url);
    const acts = document.createElement("div");
    acts.className = "ls-actions";
    const edit = document.createElement("button");
    edit.className = "icon-btn";
    edit.textContent = "···";
    edit.title = "编辑";
    edit.onclick = () => openServerDialog(i);
    const del = document.createElement("button");
    del.className = "icon-btn danger";
    del.title = "删除";
    del.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/></svg>';
    del.onclick = () => {
      if (confirm("确定删除服务器 " + (s.name || s.url) + " ？")) {
        fetch("/api/servers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "remove", index: i }),
        }).then(r => r.json()).then(res => { if (res.ok) { servers = res.servers; renderServers(); } });
      }
    };
    acts.appendChild(edit); acts.appendChild(del);
    row.appendChild(dot); row.appendChild(info); row.appendChild(acts);
    box.appendChild(row);
  });
}
function openServerDialog(idx){
  serverEditing = idx;
  document.getElementById("serverDialogTitle").textContent = idx >= 0 ? "编辑服务器" : "添加服务器";
  const s = idx >= 0 ? servers[idx] : {};
  document.getElementById("srv_url").value = s.url || "";
  document.getElementById("srv_name").value = s.name || "";
  document.getElementById("srv_user").value = s.user || "lumina-code";
  document.getElementById("srv_password").value = s.password || "";
  document.getElementById("srvNote").textContent = "";
  document.getElementById("serverOverlay").classList.add("open");
}
function closeServerDialog(){ document.getElementById("serverOverlay").classList.remove("open"); }
function saveServerDialog(){
  const payload = {
    url: document.getElementById("srv_url").value.trim(),
    name: document.getElementById("srv_name").value.trim(),
    user: document.getElementById("srv_user").value.trim(),
    password: document.getElementById("srv_password").value,
  };
  const action = serverEditing >= 0 ? "update" : "add";
  if (action === "update") payload.index = serverEditing;
  fetch("/api/servers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ action }, payload)),
  }).then(r => r.json()).then(res => {
    if (res.ok) { servers = res.servers; renderServers(); closeServerDialog(); }
    else document.getElementById("srvNote").textContent = res.message || "保存失败";
  });
}

/* ---------- models ---------- */
const MODELS = [{ id: "deepseek-v4-flash", name: "DeepSeek V4 Flash" }];
function renderModels(cfg){
  const box = document.getElementById("modelList");
  if (!box) return;
  box.innerHTML = "";
  MODELS.forEach(m => {
    const row = document.createElement("div");
    row.className = "model-row";
    const ic = document.createElement("span");
    ic.className = "m-ic";
    ic.textContent = "DS";
    const name = document.createElement("span");
    name.className = "m-name";
    name.textContent = m.name;
    const status = document.createElement("span");
    const hasKey = cfg && cfg.DEEPSEEK_API_KEY;
    status.className = "m-status" + (hasKey ? "" : " err");
    status.textContent = hasKey ? "已配置 API Key" : "未配置 API Key，点击 ··· 配置";
    const menu = document.createElement("button");
    menu.className = "icon-btn";
    menu.textContent = "···";
    menu.title = "配置";
    menu.onclick = openModelDialog;
    row.appendChild(ic); row.appendChild(name); row.appendChild(status); row.appendChild(menu);
    box.appendChild(row);
  });
}
function openModelDialog(){
  fetch("/api/config").then(r => r.json()).then(cfg => {
    Object.keys(cfg).forEach(k => {
      const el = document.getElementById("cfg_" + k);
      if (el) { if (el.type === "checkbox") el.checked = !!cfg[k]; else el.value = cfg[k] == null ? "" : cfg[k]; }
    });
    document.getElementById("modelNote").textContent = "";
    document.getElementById("modelOverlay").classList.add("open");
  });
}
function closeModelDialog(){ document.getElementById("modelOverlay").classList.remove("open"); }
function saveModelConfig(){
  const fields = {};
  document.querySelectorAll("#modelOverlay input").forEach(el => {
    const key = el.id.replace("cfg_", "");
    fields[key] = el.type === "checkbox" ? el.checked : el.value.trim();
  });
  fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  }).then(r => r.json()).then(res => {
    const note = document.getElementById("modelNote");
    note.textContent = res.ok ? "已保存到 .env，新会话将使用新配置。" : ("保存失败: " + (res.message || ""));
    if (res.ok) renderModels(fields);
  });
}
function cmpVer(a, b){
  const pa = String(a).replace(/^v/i, "").split(".").map(n => parseInt(n, 10) || 0);
  const pb = String(b).replace(/^v/i, "").split(".").map(n => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0, y = pb[i] || 0;
    if (x > y) return 1;
    if (x < y) return -1;
  }
  return 0;
}
function openExternalUrl(url){
  try {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.open_url === "function") {
      window.pywebview.api.open_url(url);
      return;
    }
  } catch (e) {}
  window.open(url, "_blank");
}
function setUpdateBadge(has){
  const wrap = document.getElementById("settingsBtnWrap");
  if (wrap) wrap.classList.toggle("has-update", !!has);
}
function checkUpdate(opts){
  const silent = opts && opts.silent;
  const btn = document.getElementById("checkUpdateBtn");
  const note = document.getElementById("updateNote");
  if (btn) btn.disabled = true;
  if (note && !silent) note.textContent = "正在检查…";
  fetch("https://api.github.com/repos/JonathanSssst/Lumina-Code/releases/latest")
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(data => {
      const latest = (data.tag_name || "").replace(/^v/i, "");
      const cur = APP_VERSION.replace(/^v/i, "");
      if (!latest) {
        if (note && !silent) note.textContent = "无法获取最新版本号。";
        return;
      }
      if (cmpVer(latest, cur) <= 0) {
        setUpdateBadge(false);
        if (note && !silent) note.textContent = "已是最新版本 (v" + APP_VERSION + ")";
        return;
      }
      setUpdateBadge(true);
      if (note) {
        note.textContent = "";
        const span = document.createElement("span");
        span.textContent = "当前 v" + APP_VERSION + "，发现新版本 " + data.tag_name + "：";
        const link = document.createElement("a");
        link.textContent = "前往 GitHub 下载";
        link.className = "update-link";
        link.href = "#";
        link.onclick = (e) => { e.preventDefault(); openExternalUrl(data.html_url || "https://github.com/JonathanSssst/Lumina-Code/releases/latest"); };
        note.appendChild(span);
        note.appendChild(link);
      }
    })
    .catch(e => { if (note && !silent) note.textContent = "检查失败: " + e.message; })
    .finally(() => { if (btn) btn.disabled = false; });
}

/* ---------- workspaces + export ---------- */
function exportSession() {
  if (!currentSession) return;
  fetch(`/api/session/${currentSession}/export?format=markdown&workspace=${encodeURIComponent(activeWorkspace)}`)
    .then(r => { if (!r.ok) throw new Error("导出失败"); return r.blob(); })
    .then(blob => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "session-" + currentSession + ".md";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    })
    .catch(e => appendMd("error", "导出失败: " + e.message));
}
/* ---------- workspaces manager ---------- */
let wsList = [];
let activeWorkspacePath = "";
function persistDefaultWorkspace(path){
  fetch("/api/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "set_default", path }),
  }).catch(() => {});
}
function refreshWorkspaces(){
  return fetch("/api/workspaces").then(r => r.json()).then(data => {
    wsList = data.workspaces || [];
    const wsSel = document.getElementById("wsSel");
    const prev = wsSel.value;
    wsSel.innerHTML = "";
    wsList.forEach(ws_ => {
      const opt = document.createElement("option");
      opt.value = ws_.path;
      opt.textContent = ws_.name;
      wsSel.appendChild(opt);
    });
    if (prev && wsList.some(w => w.path === prev)) wsSel.value = prev;
    else wsSel.value = data.default;
    activeWorkspacePath = wsSel.value;
    renderWsList();
  });
}
function renderWsList(){
  const box = document.getElementById("wsList");
  box.innerHTML = "";
  if (!wsList.length) {
    box.innerHTML = '<p class="hint" style="margin:0 0 12px">尚未配置工作区，请在下方添加一个项目目录。</p>';
    return;
  }
  wsList.forEach(ws_ => {
    const row = document.createElement("div");
    row.className = "ws-row";
    const info = document.createElement("div");
    info.className = "ws-info";
    const nm = document.createElement("div");
    nm.className = "ws-name";
    nm.textContent = ws_.name + (ws_.path === activeWorkspacePath ? "（当前）" : "");
    const pt = document.createElement("div");
    pt.className = "ws-path";
    pt.textContent = ws_.path;
    info.appendChild(nm); info.appendChild(pt);
    const act = document.createElement("div");
    act.className = "ws-actions";
    const go = document.createElement("button");
    go.textContent = "切换";
    go.onclick = () => { switchWorkspace(ws_.path); closeWsManager(); };
    const del = document.createElement("button");
    del.className = "danger";
    del.textContent = "删除";
    del.disabled = ws_.path === activeWorkspace;
    del.onclick = () => removeWs(ws_.path);
    act.appendChild(go); act.appendChild(del);
    row.appendChild(info); row.appendChild(act);
    box.appendChild(row);
  });
}
function openWsManager(){
  document.getElementById("wsNote").textContent = "";
  document.getElementById("wsPathInput").value = "";
  refreshWorkspaces().then(() => document.getElementById("wsOverlay").classList.add("open"));
}
function closeWsManager(){ document.getElementById("wsOverlay").classList.remove("open"); }
function setWsNote(text, ok){
  const note = document.getElementById("wsNote");
  note.textContent = text;
  note.style.color = ok ? "var(--ok)" : "var(--danger)";
}
async function browseWsFolder(){
  if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.pick_folder === "function") {
    try {
      const path = await window.pywebview.api.pick_folder();
      if (path) { document.getElementById("wsPathInput").value = path; return; }
    } catch (e) {}
  }
  setWsNote("当前环境无法弹出文件夹选择器，请手动输入绝对路径。", false);
}
function addWs(){
  const p = document.getElementById("wsPathInput").value.trim();
  if (!p) { setWsNote("请输入目录路径。", false); return; }
  fetch("/api/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "add", path: p }),
  }).then(r => r.json()).then(res => {
    if (res.ok) {
      setWsNote("已添加。", true);
      document.getElementById("wsPathInput").value = "";
      refreshWorkspaces();
    } else setWsNote("添加失败: " + (res.message || ""), false);
  });
}
function removeWs(path){
  fetch("/api/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "remove", path }),
  }).then(r => r.json()).then(res => {
    if (res.ok) { setWsNote("已删除。", true); refreshWorkspaces(); }
    else setWsNote("删除失败: " + (res.message || ""), false);
  });
}
loadSettings().then(() => refreshWorkspaces().then(() => connectWS(document.getElementById("wsSel").value || "")));
setTimeout(() => checkUpdate({ silent: true }), 4000);</script>
</body>
</html>"""


class WsApprover:
    """Approval via WebSocket: ask over WS, wait for the client response."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[bool] = asyncio.Queue()
        self.auto = False
        self._counter = 0

    async def approve(self, name: str, arguments: dict[str, Any], reason: str) -> bool:
        if self.auto:
            return True
        self._counter += 1
        await self.ws.send_json(
            {"type": "approval_request", "request_id": self._counter, "name": name, "reason": reason}
        )
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=300)
        except asyncio.TimeoutError:
            return False

    def submit(self, approved: bool) -> None:
        self.queue.put_nowait(approved)


class WsHooks:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def on_assistant_message(self, chunk: str) -> None:
        await self.ws.send_json({"type": "stream", "chunk": chunk})

    async def on_reasoning(self, chunk: str) -> None:
        await self.ws.send_json({"type": "reasoning", "chunk": chunk})

    async def on_tool_call(self, call) -> None:
        await self.ws.send_json(
            {"type": "tool_call", "name": call.name, "arguments": call.arguments}
        )

    async def on_tool_result(self, result) -> None:
        await self.ws.send_json(
            {
                "type": "tool_result",
                "name": result.name,
                "is_error": result.is_error,
                "content": result.content[:2000],
                "stats": result.stats,
            }
        )


def create_app(
    settings: Settings,
    workspace: Path,
    workspaces: list[Path] | None = None,
    *,
    config_env: Path | None = None,
    state_file: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="LuminaCode")
    workspace = Path(workspace).resolve()
    configured = [str(Path(p).resolve()) for p in (workspaces or [])]
    if str(workspace) not in configured:
        configured.insert(0, str(workspace))
    ws_paths: list[Path] = [Path(p) for p in dict.fromkeys(configured)]
    app.state.workspaces = ws_paths
    app.state.settings = settings
    app.state.stores: dict[str, SessionStore] = {}
    app.state.config_env = Path(config_env).resolve() if config_env else None
    app.state.state_file = Path(state_file).resolve() if state_file else None

    def env_target() -> Path:
        return app.state.config_env or (app.state.workspaces[0] / ".env")

    def _load_state() -> dict:
        try:
            return json.loads(app.state.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(data: dict) -> None:
        try:
            app.state.state_file.parent.mkdir(parents=True, exist_ok=True)
            app.state.state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _workspaces_payload() -> dict:
        return {
            "workspaces": [{"path": str(p), "name": p.name or str(p)} for p in ws_paths],
            "default": str(workspace),
        }

    def _persist_workspaces() -> None:
        try:
            write_env(env_target(), {"LUMINA_WORKSPACES": ",".join(str(p) for p in ws_paths)})
        except OSError:
            pass

    def get_store(path: Path) -> SessionStore:
        key = str(path)
        if key not in app.state.stores:
            app.state.stores[key] = SessionStore(default_db_path(path))
        return app.state.stores[key]

    def resolve_workspace(requested: str) -> Path:
        if not requested:
            return workspace
        for p in ws_paths:
            if requested in (str(p), p.name):
                return p
        return workspace

    def session_payload(store: SessionStore, sid: int) -> dict:
        s = store.get_session(sid)
        return {"id": sid, "title": s.title if s else "", "messages": s.message_count if s else 0}

    async def push_sessions(ws: WebSocket, store: SessionStore, path: Path) -> None:
        await ws.send_json(
            {"type": "sessions", "sessions": [session_payload(store, s.id) for s in store.list_sessions(path)]}
        )

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX_HTML

    @app.get("/api/workspaces")
    async def list_workspaces() -> dict:
        return _workspaces_payload()

    @app.post("/api/workspaces")
    async def mutate_workspaces(payload: dict[str, Any]) -> dict:
        action = str(payload.get("action", ""))
        raw = str(payload.get("path", "")).strip()
        if not raw:
            return {"ok": False, "message": "缺少路径参数 path"}
        p = Path(raw).expanduser().resolve()
        known = [str(w) for w in ws_paths]

        if action == "add":
            if not p.is_dir():
                return {"ok": False, "message": f"不是有效目录: {p}"}
            if str(p) not in known:
                ws_paths.append(p)
                _persist_workspaces()
            return {"ok": True, **_workspaces_payload()}

        if action == "remove":
            if str(p) == str(workspace):
                return {"ok": False, "message": "不能移除当前正在使用的工作区，请先切换到其他工作区"}
            before = len(ws_paths)
            ws_paths[:] = [w for w in ws_paths if str(w) != str(p)]
            if len(ws_paths) == before:
                return {"ok": False, "message": "工作区不在列表中"}
            _persist_workspaces()
            if app.state.state_file is not None:
                state = _load_state()
                if state.get("last_workspace") == str(p):
                    state["last_workspace"] = str(workspace)
                    _save_state(state)
            return {"ok": True, **_workspaces_payload()}

        if action == "set_default":
            if str(p) not in known:
                return {"ok": False, "message": "工作区不在列表中"}
            if app.state.state_file is not None:
                state = _load_state()
                state["last_workspace"] = str(p)
                _save_state(state)
            return {"ok": True}

        return {"ok": False, "message": f"未知操作: {action}"}

    @app.get("/api/prefs")
    async def get_prefs() -> dict:
        state = _load_state() if app.state.state_file is not None else {}
        return {"theme": state.get("theme") or "dark"}

    @app.post("/api/prefs")
    async def set_prefs(payload: dict[str, Any]) -> dict:
        theme = str(payload.get("theme", "")).lower()
        if theme not in ("dark", "light"):
            return {"ok": False, "message": "theme 必须是 dark 或 light"}
        if app.state.state_file is not None:
            state = _load_state()
            state["theme"] = theme
            _save_state(state)
        return {"ok": True, "theme": theme}

    def _default_settings() -> dict:
        return {
            "language": "zh-CN",
            "auto_approve": False,
            "shell": "auto",
            "show_reasoning": False,
            "expand_shell": False,
            "expand_edit": False,
            "color_scheme": "system",
            "theme": "system",
            "ui_font": "",
            "code_font": "",
            "term_font": "JetBrainsMono Nerd Font Mono",
            "notif_agent": True,
            "notif_permission": True,
            "notif_error": False,
            "sound_agent": "none",
            "sound_permission": "none",
            "sound_error": "none",
            "release_notes": True,
            "file_tree": False,
            "command_palette": False,
            "server_status": False,
            "custom_agents": False,
        }

    def _load_settings() -> dict:
        defaults = _default_settings()
        if app.state.state_file is None:
            return defaults
        stored = _load_state().get("settings") or {}
        return {**defaults, **stored}

    def _save_settings(data: dict) -> None:
        if app.state.state_file is None:
            return
        state = _load_state()
        state["settings"] = data
        _save_state(state)

    @app.get("/api/settings")
    async def get_settings_data() -> dict:
        return _load_settings()

    @app.post("/api/settings")
    async def set_settings_data(payload: dict[str, Any]) -> dict:
        current = _load_settings()
        merged = {**current}
        for key, value in (payload or {}).items():
            if key in current:
                merged[key] = value
        _save_settings(merged)
        return {"ok": True, "settings": merged}

    @app.get("/api/servers")
    async def list_servers() -> dict:
        servers = _load_state().get("servers", []) if app.state.state_file is not None else []
        if not isinstance(servers, list):
            servers = []
        return {"servers": servers}

    @app.post("/api/servers")
    async def mutate_servers(payload: dict[str, Any]) -> dict:
        if app.state.state_file is None:
            return {"ok": False, "message": "无状态文件，无法保存服务器"}
        state = _load_state()
        servers = state.get("servers", [])
        if not isinstance(servers, list):
            servers = []
        action = str(payload.get("action", ""))
        idx = int(payload.get("index", -1))
        if action == "add":
            url = str(payload.get("url", "")).strip()
            if not url:
                return {"ok": False, "message": "服务器 URL 不能为空"}
            entry = {
                "url": url,
                "name": str(payload.get("name", "")).strip() or url,
                "user": str(payload.get("user", "")).strip(),
                "password": str(payload.get("password", "")).strip(),
            }
            servers.append(entry)
        elif action == "update":
            if not (0 <= idx < len(servers)):
                return {"ok": False, "message": "服务器不存在"}
            for key in ("url", "name", "user", "password"):
                if key in payload:
                    servers[idx][key] = str(payload.get(key, "")).strip()
        elif action == "remove":
            if not (0 <= idx < len(servers)):
                return {"ok": False, "message": "服务器不存在"}
            servers.pop(idx)
        else:
            return {"ok": False, "message": f"未知操作: {action}"}
        state["servers"] = servers
        _save_state(state)
        return {"ok": True, "servers": servers}

    @app.get("/api/session/{sid}/export")
    async def export_session(sid: int, format: str = "markdown", workspace: str = "") -> Any:
        store = get_store(resolve_workspace(workspace))
        session = store.get_session(sid)
        if session is None:
            return JSONResponse({"error": f"会话 {sid} 不存在"}, status_code=404)
        msgs = store.get_messages(sid)
        if format == "json":
            return JSONResponse(
                {
                    "session": {"id": sid, "title": session.title, "messages": session.message_count},
                    "messages": [
                        {"role": m.role, "content": m.content or "", "tool": m.name or ""} for m in msgs
                    ],
                }
            )
        parts: list[str] = []
        for m in msgs:
            if m.role == "user" and m.content:
                parts.append(f"## User\n\n{m.content}")
            elif m.role == "assistant" and m.content:
                parts.append(f"## Assistant\n\n{m.content}")
        body = "\n\n---\n\n".join(parts) or "(empty session)"
        filename = f"session-{sid}.md"
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/config")
    async def get_config() -> dict:
        return _config_payload(app.state.settings)

    @app.post("/api/config")
    async def post_config(payload: dict[str, Any]) -> dict:
        updates: dict[str, str] = {}
        for key in _EDITABLE_KEYS:
            if key in payload:
                value = payload[key]
                if isinstance(value, bool):
                    value = "true" if value else "false"
                updates[key] = str(value)
        if not updates:
            return {"ok": False, "message": "no valid configuration fields"}
        try:
            write_env(env_target(), updates)
        except OSError as exc:
            return {"ok": False, "message": str(exc)}
        get_settings.cache_clear()
        app.state.settings = get_settings()
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, w: str = "") -> None:
        await ws.accept()
        ws_path = resolve_workspace(w)
        store = get_store(ws_path)
        approver = WsApprover(ws)
        agent = build_agent(ws_path, app.state.settings, approver, WsHooks(ws))
        current_session: int | None = None
        running: asyncio.Task | None = None

        async def run_in_background(content: str, sid: int, history: list[Message]) -> None:
            """Runs the agent in a background task so approvals stay responsive."""
            try:
                result = await agent.run(
                    content,
                    history=history,
                    persist=lambda m, sid_=sid: store.append_message(sid_, m),
                )
                await ws.send_json(
                    {
                        "type": "done",
                        "iterations": result.iterations,
                        "tool_calls": result.tool_calls_made,
                        "total_tokens": result.total_tokens,
                        "stopped_reason": result.stopped_reason,
                        "final_content": result.final_content,
                    }
                )
            except asyncio.CancelledError:
                try:
                    await ws.send_json({"type": "cancelled"})
                except Exception:  # noqa: BLE001, S110
                    pass
                raise
            except Exception as exc:  # noqa: BLE001
                await ws.send_json({"type": "error", "message": str(exc)})
            finally:
                try:
                    await push_sessions(ws, store, ws_path)
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001, S110
                    pass

        try:
            await push_sessions(ws, store, ws_path)
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                mtype = msg.get("type")

                if mtype == "list":
                    await push_sessions(ws, store, ws_path)

                elif mtype == "new_session":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    current_session = store.create_session(ws_path, "新会话")
                    agent.reset_budget()
                    await ws.send_json({"type": "session", "session": session_payload(store, current_session)})
                    await push_sessions(ws, store, ws_path)

                elif mtype == "delete_session":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    sid = int(msg.get("session_id", 0))
                    if store.get_session(sid) is None:
                        await ws.send_json({"type": "error", "message": f"会话 {sid} 不存在"})
                        continue
                    store.delete_session(sid)
                    if current_session == sid:
                        current_session = None
                        await ws.send_json({"type": "session_cleared"})
                    await push_sessions(ws, store, ws_path)

                elif mtype == "rename_session":
                    sid = int(msg.get("session_id", 0))
                    title = str(msg.get("title", "")).strip()[:60]
                    if store.get_session(sid) is None:
                        await ws.send_json({"type": "error", "message": f"会话 {sid} 不存在"})
                        continue
                    store.set_title(sid, title or "新会话")
                    await push_sessions(ws, store, ws_path)

                elif mtype == "resume":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    sid = int(msg.get("session_id", 0))
                    if store.get_session(sid) is None:
                        await ws.send_json({"type": "error", "message": f"会话 {sid} 不存在"})
                        continue
                    if current_session != sid:
                        agent.reset_budget()
                    current_session = sid
                    await ws.send_json({"type": "session", "session": session_payload(store, sid)})
                    msgs = [
                        {"role": m.role, "content": m.content or ""}
                        for m in store.get_messages(sid)
                        if m.role in ("user", "assistant") and m.content
                    ]
                    await ws.send_json({"type": "history", "messages": msgs})

                elif mtype == "message":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    if current_session is None:
                        current_session = store.create_session(ws_path, "新会话")
                        agent.reset_budget()
                        await ws.send_json({"type": "session", "session": session_payload(store, current_session)})
                    content = msg.get("content", "")
                    history = store.get_messages(current_session)
                    store.append_message(current_session, Message(role="user", content=content))
                    s = store.get_session(current_session)
                    if s and s.message_count <= 1:
                        store.set_title(current_session, content[:40])
                    running = asyncio.create_task(
                        run_in_background(content, current_session, history)
                    )

                elif mtype == "truncate":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    if current_session is None:
                        continue
                    if not store.truncate_after_user(current_session, int(msg.get("before_user", -1))):
                        await ws.send_json({"type": "error", "message": "无法回退：找不到该消息"})
                        continue
                    await push_sessions(ws, store, ws_path)

                elif mtype == "approval_response":
                    approver.submit(bool(msg.get("approved")))

                elif mtype == "cancel":
                    if running and not running.done():
                        await ws.send_json({"type": "cancelled"})
                        running.cancel()

                elif mtype == "set_auto":
                    approver.auto = bool(msg.get("value"))
        except WebSocketDisconnect:
            pass
        finally:
            if running is not None:
                running.cancel()
            await agent.aclose()

    @app.on_event("shutdown")
    async def _close_store() -> None:
        for s in app.state.stores.values():
            s.close()

    return app
