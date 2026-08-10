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
<title>LuminaCoder</title>
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
    --shadow: 0 10px 34px rgba(0,0,0,.5);
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
  body { margin: 0; display: flex; flex-direction: column;
         background: var(--bg); background-image: var(--bg-grad); background-attachment: fixed;
         color: var(--text); font-family: var(--sans);
         -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
         transition: background-color .35s ease, color .35s ease; }
  ::selection { background: var(--accent-soft); color: var(--text); }

  /* ---------- header ---------- */
  header { position: relative; display: flex; align-items: center; gap: 12px; padding: 12px 22px;
           background: var(--header-bg); backdrop-filter: blur(14px) saturate(140%);
           -webkit-backdrop-filter: blur(14px) saturate(140%);
           border-bottom: 1px solid var(--border); z-index: 10; }
  .brand { display: flex; align-items: center; gap: 10px; flex: none; }
  .brand-mark { width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center;
    background: linear-gradient(135deg, var(--accent-2), var(--accent));
    box-shadow: 0 0 0 1px rgba(245,177,61,.28), 0 6px 18px rgba(245,177,61,.22); }
  .brand-mark svg { width: 15px; height: 15px; }
  header strong { font-size: 15px; font-weight: 650; letter-spacing: .2px; }
  .sel-group { display: flex; gap: 8px; align-items: center; }
  .btn-group { display: flex; gap: 2px; align-items: center; padding: 3px;
    border: 1px solid var(--border); border-radius: 10px; background: rgba(127,127,127,.05); }
  header .spacer { flex: 1; }

  select, button, input { font-family: var(--sans); color: var(--text);
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

  /* ---------- main / log ---------- */
  #main { flex: 1; overflow-y: auto; scroll-behavior: smooth; }
  #log { max-width: 820px; margin: 0 auto; padding: 28px 22px 44px; }

  .msg { margin-bottom: 16px; line-height: 1.65; font-size: 14px; word-break: break-word;
    animation: rise .32s ease both; }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  .msg .bubble { display: inline-block; padding: 10px 15px; border-radius: 15px; }
  .msg.user { display: flex; justify-content: flex-end; }
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
    padding: 10px 0; outline: none; font-family: var(--sans); }
  #input::placeholder { color: var(--faint); }
  #send { background: var(--accent); border: none; color: var(--on-accent); border-radius: 10px;
    padding: 9px 17px; cursor: pointer; font-weight: 600; font-size: 13.5px;
    display: flex; align-items: center; gap: 6px; box-shadow: 0 4px 14px rgba(245,177,61,.3); }
  #send:hover { filter: brightness(1.06); }
  #send:active { transform: translateY(1px); }
  #send:disabled { opacity: .4; cursor: not-allowed; box-shadow: none; }
  #send.stopping { background: var(--danger); box-shadow: 0 4px 14px rgba(248,113,113,.3); }
  #send svg { width: 16px; height: 16px; }

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

  ::-webkit-scrollbar { width: 11px; height: 11px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 6px;
    border: 3px solid transparent; background-clip: padding-box; }
  ::-webkit-scrollbar-thumb:hover { background: var(--muted); background-clip: padding-box; }
</style>
<meta name="color-scheme" content="dark light"/>
</head>
<body>
<header>
  <div class="brand">
    <span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="#1a1208"><path d="M16 5l2.6 7.2L26 15l-7.4 2.8L16 25l-2.6-7.2L6 15l7.4-2.8L16 5z"/></svg></span>
    <strong>LuminaCoder</strong>
  </div>
  <div class="sel-group">
    <select id="wsSel" onchange="switchWorkspace(this.value)" title="工作区"></select>
    <button class="icon-btn" onclick="openWsManager()" title="选择 / 管理工作区"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/></svg></button>
    <select id="sessions" onchange="switchSession(this.value)" title="会话"></select>
  </div>
  <div class="btn-group">
    <button class="icon-btn" onclick="newSession()" title="新建会话"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg></button>
    <button class="icon-btn" onclick="renameSession()" title="重命名"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button>
    <button class="icon-btn" onclick="exportSession()" title="导出 Markdown"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg></button>
    <button class="icon-btn danger" onclick="deleteSession()" title="删除会话"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/></svg></button>
  </div>
  <span class="spacer"></span>
  <span id="tokStat" class="stat" style="display:none;"></span>
  <button class="icon-btn" id="themeBtn" onclick="toggleTheme()" title="切换主题">
    <svg class="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>
    <svg class="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
  </button>
  <button class="icon-btn" onclick="openSettings()" title="设置"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg></button>
  <label class="toggle"><input id="autoApprove" type="checkbox"/><span>自动批准</span></label>
</header>
<div id="main"><div id="log"></div></div>
<div id="inputbar"><div id="inputwrap">
  <input id="input" placeholder="描述任务，例如：帮我修复失败的测试" autofocus/>
  <button id="send" onclick="sendBtnClick()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>发送</button>
</div></div>
<div id="settingsOverlay" class="modal-overlay" onclick="if(event.target===this)closeSettings()">
  <div class="modal">
    <h3>设置</h3>
    <p class="hint">修改将写入工作区 <code>.env</code> 文件。保存后新会话生效；运行中的任务不受影响。</p>
    <div class="field"><label>API Key</label><input id="cfg_DEEPSEEK_API_KEY" type="password" autocomplete="off"/></div>
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
    <div class="actions">
      <button onclick="closeSettings()">取消</button>
      <button class="save" onclick="saveSettings()">保存</button>
    </div>
    <div id="saveNote" class="save-note"></div>
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
const sel = document.getElementById("sessions");
let busy = false;
let currentSession = null;
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
  ws.onopen = () => ws.send(JSON.stringify({ type: "list" }));
  ws.onmessage = (e) => handleWSMessage(JSON.parse(e.data));
}

function setBusy(b){
  busy = b;
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
function appendMd(cls, text, bubble){
  const div = document.createElement("div");
  div.className = "msg " + cls;
  const inner = document.createElement("div");
  inner.className = "bubble markdown";
  inner.innerHTML = renderMarkdown(text);
  div.appendChild(inner);
  log.appendChild(div);
  scrollBottom();
  return inner;
}
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
  else if (m.type === "session_cleared") { currentSession = null; tokenUsed = 0; updateTok(); log.innerHTML = ""; }
  else if (m.type === "history") {
    m.messages.forEach(msg => {
      if (msg.role === "user") appendMd("user", msg.content);
      else if (msg.role === "assistant") appendMd("assistant", msg.content);
    });
  } else if (m.type === "reasoning") {
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
      const inner = document.createElement("div");
      inner.className = "bubble markdown";
      div.appendChild(inner);
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
    resetStream();
    setBusy(false);
    tokenUsed += m.total_tokens || 0;
    updateTok();
    let hint = "";
    if (m.stopped_reason === "budget_exhausted") hint = " （已达累计 token 预算，可在 .env 调大 LUMINA_TOKEN_BUDGET）";
    appendStat("[done] iter=" + m.iterations + " tools=" + m.tool_calls + " tokens=" + m.total_tokens + " stop=" + m.stopped_reason + hint);
  } else if (m.type === "cancelled") {
    stopThinkTimer(); resetStream(); setBusy(false);
    appendStat("[stopped] 任务已手动停止");
  } else if (m.type === "error") {
    stopThinkTimer(); resetStream(); setBusy(false);
    appendMd("error", "错误: " + m.message);
  }
}

function switchWorkspace(value){
  if (busy) return;
  currentSession = null;
  log.innerHTML = "";
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
  tokenUsed = 0; updateTok();
  connectWS(value);
  persistDefaultWorkspace(value);
}

function renderSessions(sessions) {
  const prev = currentSession;
  sel.innerHTML = "";
  sessions.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = "#" + s.id + " " + (s.title || "").slice(0, 24) + " (" + s.messages + ")";
    sel.appendChild(opt);
  });
  if (prev != null && sessions.some(s => s.id === prev)) sel.value = prev;
}
function respond(id, approved) {
  ws.send(JSON.stringify({ type: "approval_response", request_id: id, approved }));
}
function switchSession(id) {
  if (busy || !id) return;
  log.innerHTML = "";
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
  tokenUsed = 0; updateTok();
  ws.send(JSON.stringify({ type: "resume", session_id: Number(id) }));
}
function newSession() {
  if (busy) return;
  ws.send(JSON.stringify({ type: "new_session" }));
}
function renameSession() {
  if (busy || !currentSession) return;
  const cur = (sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "").replace(/^#[\\d]+ /, "");
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
});

/* ---------- theme toggle ---------- */
let theme = localStorage.getItem("lumina-theme") || "dark";
document.documentElement.setAttribute("data-theme", theme);
function updateThemeBtn(){ /* theme icon toggled via CSS based on [data-theme] */ }
updateThemeBtn();
function toggleTheme(){
  theme = theme === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("lumina-theme", theme);
  updateThemeBtn();
}

/* ---------- settings panel ---------- */
function openSettings(){
  document.getElementById("saveNote").textContent = "";
  fetch("/api/config").then(r => r.json()).then(cfg => {
    Object.keys(cfg).forEach(k => {
      const el = document.getElementById("cfg_" + k);
      if (el) { if (el.type === "checkbox") el.checked = !!cfg[k]; else el.value = cfg[k] == null ? "" : cfg[k]; }
    });
  });
  document.getElementById("settingsOverlay").classList.add("open");
}
function closeSettings(){ document.getElementById("settingsOverlay").classList.remove("open"); }
function saveSettings(){
  const fields = {};
  document.querySelectorAll("#settingsOverlay input").forEach(el => {
    const key = el.id.replace("cfg_", "");
    fields[key] = el.type === "checkbox" ? el.checked : el.value.trim();
  });
  fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  }).then(r => r.json()).then(res => {
    document.getElementById("saveNote").textContent =
      res.ok ? "已保存到 .env，新会话将使用新配置。" : ("保存失败: " + (res.message || ""));
  });
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
refreshWorkspaces().then(() => connectWS(document.getElementById("wsSel").value || ""));</script>
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
    app = FastAPI(title="LuminaCoder")
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
