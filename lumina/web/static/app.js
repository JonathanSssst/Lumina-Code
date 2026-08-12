
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
    renderTodos([]);
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

/* ---------- session usage ring (top-right) + stats popup ---------- */
const USAGE_RING_C = 119.38;
let usageStats = null;
let usagePopOpen = false;
function fmtNum(n){
  const v = Number(n) || 0;
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "k";
  return String(v);
}
function usageFraction(st){
  const total = st && st.usage ? (st.usage.total || 0) : 0;
  const limit = st && st.context_limit ? st.context_limit : 0;
  return { total, limit, frac: limit && total ? Math.min(1, total / limit) : 0 };
}
function updateUsageRing(st){
  const btn = document.getElementById("usageRingBtn");
  const val = document.getElementById("usageRingVal");
  if (!btn || !val) return;
  const bar = btn.querySelector(".usage-ring-bar");
  const { total, limit, frac } = usageFraction(st);
  if (bar) bar.style.strokeDashoffset = String(USAGE_RING_C * (1 - frac));
  btn.classList.toggle("none", !frac);
  val.textContent = !st ? "–" : total > 0 ? fmtNum(total) : "0";
  if (st) val.title = "total " + total + " / " + (limit || "∞");
}
function fetchSessionStats(){
  if (!currentSession) { usageStats = null; updateUsageRing(null); return; }
  fetch(`/api/session/${currentSession}/stats?workspace=${encodeURIComponent(activeWorkspace)}`)
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(st => { usageStats = st; updateUsageRing(st); if (usagePopOpen) renderUsagePop(); })
    .catch(() => { updateUsageRing(null); });
}
function toggleUsagePop(){
  const pop = document.getElementById("usagePop");
  if (!pop) return;
  usagePopOpen = !usagePopOpen;
  pop.hidden = !usagePopOpen;
  if (usagePopOpen) fetchSessionStats();
  else hideUsageTrend();
}
let usageTrendOpen = false;
function hideUsageTrend(){
  const chart = document.getElementById("usageTrend");
  if (chart) chart.hidden = true;
  usageTrendOpen = false;
}
function toggleUsageTrend(){
  const chart = document.getElementById("usageTrend");
  if (!chart) return;
  usageTrendOpen = !usageTrendOpen;
  chart.hidden = !usageTrendOpen;
  if (usageTrendOpen) renderUsageTrend();
}
function renderUsageTrend(){
  const chart = document.getElementById("usageTrend");
  if (!chart) return;
  chart.innerHTML = '<div class="usage-hint" style="border:none;padding:0">加载趋势…</div>';
  fetch("/api/usage/trend?workspace=" + encodeURIComponent(activeWorkspace))
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(data => {
      const pts = (data.points || []).slice(0, 30);
      chart.innerHTML = "";
      if (!pts.length) {
        chart.innerHTML = '<div class="usage-hint" style="border:none;padding:0">暂无用量数据</div>';
        return;
      }
      const max = Math.max(...pts.map(p => p.total_tokens), 1);
      pts.forEach(p => {
        const col = document.createElement("div");
        col.className = "trend-col";
        col.title = (p.title || "会话 #" + p.session_id) + " · " + fmtNum(p.total_tokens) + " tokens" + (p.updated_at ? " · " + p.updated_at : "");
        col.onclick = () => { toggleUsagePop(); switchSession(p.session_id); };
        const bar = document.createElement("div");
        bar.className = "trend-bar";
        bar.style.height = Math.max(6, Math.round(p.total_tokens / max * 88)) + "px";
        const sub = document.createElement("div");
        sub.className = "trend-sub";
        sub.textContent = "#" + p.session_id;
        col.appendChild(bar); col.appendChild(sub);
        chart.appendChild(col);
      });
    })
    .catch(() => { chart.innerHTML = '<div class="usage-hint" style="border:none;padding:0">加载失败</div>'; });
}
function usageHeroRing(st){
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 44 44");
  svg.setAttribute("class", "usage-ring-svg");
  const { frac } = usageFraction(st);
  const track = document.createElementNS(ns, "circle");
  track.setAttribute("class", "usage-ring-track");
  track.setAttribute("cx", "22"); track.setAttribute("cy", "22"); track.setAttribute("r", "19");
  const bar = document.createElementNS(ns, "circle");
  bar.setAttribute("class", "usage-ring-bar");
  bar.setAttribute("cx", "22"); bar.setAttribute("cy", "22"); bar.setAttribute("r", "19");
  bar.setAttribute("style", "stroke-dashoffset:" + (USAGE_RING_C * (1 - frac)));
  svg.appendChild(track); svg.appendChild(bar);
  return { svg, frac };
}
function renderUsagePop(){
  const body = document.getElementById("usagePopBody");
  if (!body) return;
  body.innerHTML = "";
  if (!usageStats) {
    body.innerHTML = '<div class="usage-hint">暂无用量数据。运行一次任务后，这里会显示 token 消耗与费用估算。</div>';
    return;
  }
  const st = usageStats;
  const u = st.usage || {};
  const { total, limit, frac } = usageFraction(st);
  const hero = document.createElement("div");
  hero.className = "usage-hero";
  const ringWrap = document.createElement("span");
  ringWrap.className = "usage-ring-wrap";
  ringWrap.appendChild(usageHeroRing(st).svg);
  const info = document.createElement("div");
  info.className = "usage-hero-info";
  const t = document.createElement("div");
  t.className = "usage-hero-title";
  t.textContent = st.title || ("会话 #" + st.id);
  const sub = document.createElement("div");
  sub.className = "usage-hero-sub";
  sub.textContent = fmtNum(total) + " / " + (limit ? fmtNum(limit) + " tokens" : "∞ tokens") +
    (frac > 0 ? " · " + Math.round(frac * 100) + "%" : "");
  const bar = document.createElement("div");
  bar.className = "usage-bar";
  const fill = document.createElement("div");
  fill.className = "usage-bar-fill";
  fill.style.width = Math.round(frac * 100) + "%";
  bar.appendChild(fill);
  info.appendChild(t); info.appendChild(sub); info.appendChild(bar);
  hero.appendChild(ringWrap); hero.appendChild(info);
  body.appendChild(hero);
  const rows = document.createElement("div");
  rows.className = "usage-rows";
  const mkSec = (label) => {
    const s = document.createElement("div");
    s.className = "usage-sec";
    s.textContent = label;
    rows.appendChild(s);
  };
  const mk = (label, value, opts) => {
    const r = document.createElement("div");
    r.className = "usage-row";
    const l = document.createElement("span");
    l.className = "u-label";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "u-value" + (opts && opts.hl ? " hl" : "");
    if (opts && opts.dim) {
      v.textContent = opts.value || "";
      const d = document.createElement("span");
      d.className = "dim";
      d.textContent = opts.dim;
      v.appendChild(d);
    } else {
      v.textContent = value;
    }
    r.appendChild(l); r.appendChild(v);
    rows.appendChild(r);
  };
  mkSec("令牌");
  mk("总 tokens", fmtNum(u.total || 0), {
    hl: true, value: fmtNum(u.total || 0), dim: limit ? " / " + fmtNum(limit) : "",
  });
  mk("输入 / 输出", fmtNum(u.prompt || 0) + " / " + fmtNum(u.completion || 0));
  mk("推理 / 缓存", fmtNum(u.reasoning || 0) + " / " + fmtNum(u.cached || 0));
  mkSec("活动");
  mk("消息数", (st.messages || 0) + "（用户 " + (st.counts ? st.counts.user : 0) +
    " · 助手 " + (st.counts ? st.counts.assistant : 0) + " · 工具 " + (st.counts ? st.counts.tool : 0) + "）");
  mk("迭代 / 工具调用", (st.iterations || 0) + " / " + (st.tool_calls || 0));
  mkSec("费用");
  mk("费用估算", "¥" + (st.cost ? st.cost.value.toFixed(4) : "0.0000") + "（¥" +
    (st.cost ? st.cost.rate_per_m : 2) + "/1M tokens）");
  if (st.created_at || st.updated_at) {
    mkSec("时间");
    mk("创建 / 更新", (st.created_at || "–") + " / " + (st.updated_at || "–"));
  }
  body.appendChild(rows);
  const hint = document.createElement("div");
  hint.className = "usage-hint";
  hint.textContent = "费用为估算值，按总量 ¥2 / 1M tokens 计算，不代表最终账单。";
  body.appendChild(hint);
}

function scrollBottom(smooth){
  main.scrollTo({ top: main.scrollHeight, behavior: smooth === false ? "instant" : "smooth" });
}

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
  let s = esc(String(src || "").replace(/\r\n/g, "\n"));
  const stash = [];
  const key = () => "\u0000" + stash.length + "\u0000";
  s = s.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (m, lang, code) => { const k = key(); stash.push("<pre><code>"+code+"</code></pre>"); return k; });
  s = s.replace(/`([^`\n]+)`/g, (m, c) => { const k = key(); stash.push("<code>"+c+"</code>"); return k; });
  s = s.replace(/\*\*([^*]+)\*\*/g, (m, t) => "<strong>"+t+"</strong>");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (m, t, u) => '<a href="'+u+'" target="_blank" rel="noopener noreferrer">'+t+"</a>");
  const lines = s.split("\n");
  let out = "";
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { out += "<h"+h[1].length+">"+h[2]+"</h"+h[1].length+">"; i++; continue; }
    if (/^\u0000\d+\u0000$/.test(line.trim())) { out += stash[+line.trim().replace(/\u0000/g,"")] || ""; i++; continue; }
    if (/^&gt; /.test(line)) { const q=[]; while (i<lines.length && /^&gt; /.test(lines[i])) { q.push(lines[i].replace(/^&gt; /,"")); i++; } out += "<blockquote>"+q.join("<br>")+"</blockquote>"; continue; }
    if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { out += "<hr/>"; i++; continue; }
    if (/^[-*] /.test(line)) { const it=[]; while (i<lines.length && /^[-*] /.test(lines[i])) { it.push(lines[i].replace(/^[-*] /,"")); i++; } out += "<ul>"+it.map(x=>"<li>"+x+"</li>").join("")+"</ul>"; continue; }
    if (/^\d+\. /.test(line)) { const it=[]; while (i<lines.length && /^\d+\. /.test(lines[i])) { it.push(lines[i].replace(/^\d+\. /,"")); i++; } out += "<ol>"+it.map(x=>"<li>"+x+"</li>").join("")+"</ol>"; continue; }
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
  out = out.replace(/\u0000(\d+)\u0000/g, (m, n) => stash[+n] || "");
  return out;
}

/* ---------- DOM helpers ---------- */
let bulkLoading = false;
function appendMd(cls, text, smooth){
  const div = document.createElement("div");
  div.className = "msg " + cls;
  if (cls === "user") { div.dataset.uindex = userCounter++; div.dataset.text = text; }
  else if (cls === "assistant") div.dataset.text = text;
  const inner = document.createElement("div");
  inner.className = "bubble markdown";
  inner.innerHTML = renderMarkdown(text);
  div.appendChild(inner);
  log.appendChild(div);
  scrollBottom(smooth);
  if (cls === "user") rebuildToc();
  if ((cls === "user" || cls === "assistant") && !bulkLoading) refreshMsgActions();
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
function refreshMsgActions(){
  document.querySelectorAll(".msg-actions").forEach(b => b.remove());
  if (busy) return;
  const msgs = document.querySelectorAll("#log .msg.user, #log .msg.assistant");
  const last = msgs[msgs.length - 1];
  if (last) last.appendChild(buildMsgActions(last, last.classList.contains("user") ? "user" : "assistant"));
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
    if (text) text += "\n";
    text += lines.join("\n");
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
function ensureThinking(){
  if (thinkingEl) return thinkingEl;
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
  return thinkingEl;
}

/* ---------- websocket ---------- */
function handleWSMessage(m) {
  if (m.type === "sessions") renderSessions(m.sessions);
  else if (m.type === "session") { currentSession = m.session.id; tokenUsed = 0; updateTok(); renderSessions(sessionsData); fetchSessionStats(); }
  else if (m.type === "session_cleared") { currentSession = null; tokenUsed = 0; updateTok(); usageStats = null; updateUsageRing(null); usagePopOpen = false; const up = document.getElementById("usagePop"); if (up) up.hidden = true; log.innerHTML = ""; userCounter = 0; editingUi = null; hideEditbar(); rebuildToc(); }
  else if (m.type === "history") {
    userCounter = 0;
    bulkLoading = true;
    log.classList.add("settle");
    m.messages.forEach(msg => {
      if (msg.role === "user") appendMd("user", msg.content, false);
      else if (msg.role === "assistant") appendMd("assistant", msg.content, false);
    });
    log.classList.remove("settle");
    bulkLoading = false;
    refreshMsgActions();
    scrollBottom(false);
  } else if (m.type === "reasoning") {
    if (!settings.show_reasoning) return;
    thinkingEl = ensureThinking();
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
      log.appendChild(div);
      refreshMsgActions();
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
      line.textContent = "\n[" + (m.is_error ? "error" : "ok") + "]\n" + (m.content || "");
      opsPending.appendChild(line);
      opsPending = null;
    }
    scrollBottom();
  } else if (m.type === "approval_request") {
    if (document.getElementById("autoApprove").checked) { respond(m.request_id, true); return; }
    notifyUser("需要批准", m.name + (m.arguments && m.arguments.command ? ": " + m.arguments.command : ""), "permission");
    const box = document.createElement("div");
    box.className = "approval";
    const args = m.arguments || {};
    const cmdTxt = String(args.command || args.content || args.path || args.url || "").trim();
    const title = document.createElement("div");
    title.className = "approval-title";
    title.textContent = "需要批准: " + m.name;
    box.appendChild(title);
    if (m.reason) {
      const reason = document.createElement("div");
      reason.className = "approval-reason";
      reason.textContent = m.reason;
      box.appendChild(reason);
    }
    if (cmdTxt) {
      const pre = document.createElement("pre");
      pre.className = "approval-cmd";
      pre.textContent = cmdTxt;
      box.appendChild(pre);
    }
    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const yes = document.createElement("button");
    yes.className = "ok"; yes.textContent = "批准";
    yes.onclick = () => { box.textContent = "[已批准] " + m.name + (cmdTxt ? " " + cmdTxt : ""); respond(m.request_id, true); };
    const no = document.createElement("button");
    no.className = "no"; no.textContent = "拒绝";
    no.onclick = () => { box.textContent = "[已拒绝] " + m.name + (cmdTxt ? " " + cmdTxt : ""); box.classList.add("err"); respond(m.request_id, false); };
    actions.appendChild(yes); actions.appendChild(no);
    box.appendChild(actions);
    log.appendChild(box);
    scrollBottom();
  } else if (m.type === "todo") {
    renderTodos(m.todos || []);
  } else if (m.type === "done") {
    stopThinkTimer();
    finalizeStreamText();
    resetStream();
    setBusy(false);
    refreshMsgActions();
    tokenUsed += m.total_tokens || 0;
    updateTok();
    let hint = "";
    if (m.stopped_reason === "budget_exhausted") hint = " （已达累计 token 预算，可在 .env 调大或移除 LUMINA_TOKEN_BUDGET，0 为不限制）";
    else if (m.stopped_reason === "iterations_exhausted") hint = " （已达最大迭代次数，可在 .env 调大或移除 LUMINA_MAX_ITERATIONS，0 为不限制）";
    appendStat("[done] iter=" + m.iterations + " tools=" + m.tool_calls + " tokens=" + m.total_tokens + " stop=" + m.stopped_reason + hint);
    if (m.stopped_reason === "budget_exhausted" || m.stopped_reason === "iterations_exhausted" || m.stopped_reason === "auto_fix_exhausted") {
      const row = document.createElement("div");
      row.className = "msg stat";
      const btn = document.createElement("button");
      btn.className = "stat-btn";
      btn.textContent = "继续执行（断点续跑）";
      btn.onclick = () => {
        if (busy || !currentSession) return;
        btn.disabled = true;
        btn.textContent = "正在继续…";
        setBusy(true);
        stopThinkTimer();
        thinkingEl = null; resetStream(); resetOps();
        appendStat("[continue] 断点续跑中…");
        ws.send(JSON.stringify({ type: "continue" }));
      };
      row.appendChild(btn);
      log.appendChild(row);
      scrollBottom();
    }
    fetchSessionStats();
    notifyUser("任务完成", "迭代 " + m.iterations + " · 工具 " + m.tool_calls + " · tokens " + m.total_tokens, "agent");
  } else if (m.type === "cancelled") {
    stopThinkTimer(); finalizeStreamText(); resetStream(); setBusy(false); refreshMsgActions();
    appendStat("[stopped] 任务已手动停止");
    notifyUser("任务已停止", "已手动停止", "agent");
  } else if (m.type === "error") {
    stopThinkTimer(); finalizeStreamText(); resetStream(); setBusy(false); refreshMsgActions();
    appendMd("error", "错误: " + m.message);
    notifyUser("发生错误", m.message, "error");
  } else if (m.type === "terminal_output") {
    if (m.exit_code === 0) termAppend(m.output || "(无输出)", "out");
    else termAppend(m.output || "(无输出)", "err");
    termAppend("[exit " + m.exit_code + "]", m.exit_code === 0 ? "ok" : "err");
    termSetStatus("");
  }
}

/* ---------- todo list (a bar attached above the input box) ---------- */
const TODO_ICON = {
  pending: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/></svg>',
  in_progress: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a9 9 0 1 1-9 9"/><circle cx="12" cy="12" r="2.2"/></svg>',
  completed: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="currentColor"/><path d="M8.2 12.4l2.6 2.6 5.2-6" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  cancelled: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></svg>'
};
const TODO_SPIN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 3a9 9 0 1 1-9 9"/></svg>';
let todoCard = null, todoCurEl = null, todoCountEl = null, todoBodyEl = null;
let todoCurText = "", todoHideTimer = null;

function currentTodo(todos){
  const ip = todos.find(t => t.status === "in_progress");
  return ip || todos.find(t => t.status === "pending") || null;
}
function ensureTodoCard(bar){
  if (todoCard) return;
  todoCard = document.createElement("div");
  todoCard.className = "todo-card";
  const head = document.createElement("button");
  head.type = "button";
  head.className = "todo-head";
  head.onclick = () => bar.classList.toggle("open");
  const spin = document.createElement("span");
  spin.className = "todo-spin";
  spin.innerHTML = TODO_SPIN;
  const label = document.createElement("span");
  label.className = "todo-label";
  label.textContent = "当前待办";
  todoCountEl = document.createElement("span");
  todoCountEl.className = "todo-count";
  label.appendChild(todoCountEl);
  todoCurEl = document.createElement("span");
  todoCurEl.className = "todo-cur";
  const chev = document.createElement("span");
  chev.className = "todo-chev";
  chev.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';
  head.appendChild(spin); head.appendChild(label); head.appendChild(todoCurEl); head.appendChild(chev);
  todoBodyEl = document.createElement("div");
  todoBodyEl.className = "todo-body";
  todoCard.appendChild(head); todoCard.appendChild(todoBodyEl);
  bar.appendChild(todoCard);
}
function setCurTodo(text){
  if (todoCurText === text) return;
  todoCurText = text;
  clearTimeout(todoCurEl._t);
  todoCurEl.style.transition = "opacity .18s ease, transform .18s ease";
  todoCurEl.style.opacity = "0";
  todoCurEl.style.transform = "translateY(4px)";
  todoCurEl._t = setTimeout(() => {
    todoCurEl.textContent = text;
    todoCurEl.style.opacity = "1";
    todoCurEl.style.transform = "translateY(0)";
  }, 180);
}
function showTodoBar(bar){
  clearTimeout(todoHideTimer);
  bar.classList.remove("hide-anim");
  if (!bar.hidden) return;
  bar.hidden = false;
  bar.classList.remove("show-anim");
  void bar.offsetWidth;
  bar.classList.add("show-anim");
}
function hideTodoBar(bar){
  if (bar.hidden) return;
  bar.classList.remove("show-anim");
  bar.classList.add("hide-anim");
  clearTimeout(todoHideTimer);
  todoHideTimer = setTimeout(() => {
    bar.classList.remove("hide-anim", "show-anim");
    bar.hidden = true;
    bar.innerHTML = "";
    todoCard = null; todoCurEl = null; todoCountEl = null; todoBodyEl = null;
    todoCurText = "";
  }, 220);
}
function renderTodos(todos){
  const bar = document.getElementById("todobar");
  if (!bar) return;
  if (!todos || !todos.length) { hideTodoBar(bar); return; }
  const cur = currentTodo(todos);
  if (!cur) { hideTodoBar(bar); return; }
  ensureTodoCard(bar);
  showTodoBar(bar);
  const done = todos.filter(t => t.status === "completed").length;
  todoCountEl.textContent = "（" + done + "/" + todos.length + "）：";
  setCurTodo(cur.content);
  todoBodyEl.innerHTML = "";
  todos.forEach((t, i) => {
    const st = t.status || "pending";
    const row = document.createElement("div");
    row.className = "todo-item " + st;
    const box = document.createElement("span");
    box.className = "todo-box";
    box.innerHTML = TODO_ICON[st] || TODO_ICON.pending;
    const txt = document.createElement("span");
    txt.className = "todo-txt";
    txt.textContent = (i + 1) + ". " + (t.content || "");
    row.appendChild(box); row.appendChild(txt);
    todoBodyEl.appendChild(row);
  });
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
  usageStats = null; updateUsageRing(null);
  const up = document.getElementById("usagePop"); if (up) up.hidden = true; usagePopOpen = false;
  connectWS(value);
  persistDefaultWorkspace(value);
}

const SESSION_GROUPS = [
  { key: "today", label: "今天" },
  { key: "yesterday", label: "昨天" },
  { key: "week", label: "本周" },
  { key: "earlier", label: "更早" },
];
function sessionGroupOf(updatedAt){
  if (!updatedAt) return "earlier";
  const d = new Date(updatedAt.replace(" ", "T"));
  if (isNaN(d.getTime())) return "earlier";
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOf = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dayDiff = Math.round((startToday - startOf) / 86400000);
  if (dayDiff <= 0) return "today";
  if (dayDiff === 1) return "yesterday";
  const monday = new Date(startToday);
  monday.setDate(startToday.getDate() - ((startToday.getDay() + 6) % 7));
  return startOf >= monday ? "week" : "earlier";
}
function renderSessions(sessions) {
  sessionsData = sessions || [];
  document.getElementById("sideCnt").textContent = sessionsData.length ? "· " + sessionsData.length : "";
  const list = document.getElementById("sessionList");
  list.innerHTML = "";
  const buckets = {};
  SESSION_GROUPS.forEach(g => buckets[g.key] = []);
  sessionsData.forEach(s => { (buckets[sessionGroupOf(s.updated_at)] || buckets.earlier).push(s); });
  SESSION_GROUPS.forEach(g => {
    const items = buckets[g.key];
    if (!items.length) return;
    const head = document.createElement("div");
    head.className = "session-group";
    head.textContent = g.label;
    list.appendChild(head);
    items.forEach(s => {
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
  });
}
function sessionSearchInput(){
  const q = document.getElementById("sessionSearch").value.trim();
  clearTimeout(window.__sessionSearchTimer);
  if (!q) {
    hideSessionSearch();
    return;
  }
  window.__sessionSearchTimer = setTimeout(() => runSessionSearch(q), 220);
}
function runSessionSearch(q){
  const box = document.getElementById("searchResults");
  fetch("/api/search?q=" + encodeURIComponent(q) + "&workspace=" + encodeURIComponent(activeWorkspace))
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(data => {
      box.innerHTML = "";
      box.style.display = "";
      const results = data.results || [];
      if (!results.length) {
        box.innerHTML = '<div class="sr-empty">没有匹配的消息</div>';
        return;
      }
      results.forEach(m => {
        const item = document.createElement("div");
        item.className = "sr-item";
        item.onclick = () => { hideSessionSearch(); switchSession(m.session_id); };
        const t = document.createElement("div"); t.className = "sr-title";
        t.textContent = (m.role === "assistant" ? "AI · " : "") + (m.title || "会话 #" + m.session_id);
        const s = document.createElement("div"); s.className = "sr-snip";
        s.textContent = m.snippet || "";
        item.appendChild(t); item.appendChild(s);
        box.appendChild(item);
      });
    })
    .catch(() => {
      box.innerHTML = '<div class="sr-empty">搜索失败</div>';
      box.style.display = "";
    });
}
function hideSessionSearch(){
  const box = document.getElementById("searchResults");
  box.innerHTML = "";
  box.style.display = "none";
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
  usageStats = null; updateUsageRing(null);
  const up = document.getElementById("usagePop"); if (up) up.hidden = true; usagePopOpen = false;
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
  requestNotifPermission();
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
  if (fileRefMatches.length) {
    if (e.key === "ArrowDown") { e.preventDefault(); fileRefIdx = (fileRefIdx + 1) % fileRefMatches.length; paintFileRef(); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); fileRefIdx = (fileRefIdx - 1 + fileRefMatches.length) % fileRefMatches.length; paintFileRef(); return; }
    if (e.key === "Enter") { e.preventDefault(); if (fileRefMatches[fileRefIdx]) insertFileRef(fileRefMatches[fileRefIdx]); return; }
    if (e.key === "Tab") { e.preventDefault(); if (fileRefMatches[fileRefIdx]) insertFileRef(fileRefMatches[fileRefIdx]); return; }
    if (e.key === "Escape") { hideFileRefPop(); return; }
  }
  if (e.key === "Enter") send();
  else if (e.key === "ArrowUp") { if (inputHistory.length && histIndex > 0) { histIndex--; input.value = inputHistory[histIndex]; } }
  else if (e.key === "ArrowDown") { if (histIndex < inputHistory.length) { histIndex++; input.value = histIndex < inputHistory.length ? inputHistory[histIndex] : ""; } }
});
input.addEventListener("input", onFileRefInput);
const sessionSearchInputEl = document.getElementById("sessionSearch");
if (sessionSearchInputEl) {
  sessionSearchInputEl.addEventListener("input", sessionSearchInput);
  sessionSearchInputEl.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { sessionSearchInputEl.value = ""; hideSessionSearch(); }
    if (e.key === "Enter") { const el = document.querySelector("#searchResults .sr-item"); if (el) el.click(); }
  });
}
document.getElementById("autoApprove").addEventListener("change", (e) => {
  ws.send(JSON.stringify({ type: "set_auto", value: e.target.checked }));
  settings.auto_approve = e.target.checked;
  persistSettings();
});

/* ---------- theme ---------- */
let settings = {};
let settingsReady = false;
const APP_VERSION = "1.0.4";
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
  const named = settings.theme && settings.theme !== "system" ? settings.theme : "";
  if (named) document.documentElement.setAttribute("data-theme-style", named);
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
  showFileTreePanel(!!settings.file_tree);
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
  if (btn.dataset.pane === "pane-mcp") renderMcp();
  if (btn.dataset.pane === "pane-skills") renderSkills();
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
  // Called without an argument (on load / tab switch): fetch the live
  // config first, otherwise the status would always read "未配置 API Key".
  if (!cfg) {
    fetch("/api/config").then(r => r.json()).then(renderModels);
    return;
  }
  const box = document.getElementById("modelList");
  if (!box) return;
  box.innerHTML = "";
  MODELS.forEach(m => {
    const row = document.createElement("div");
    row.className = "model-row";
    const ic = document.createElement("span");
    ic.className = "m-ic";
    ic.textContent = m.id === "deepseek-v4-flash" ? "DS" : "AI";
    const name = document.createElement("span");
    name.className = "m-name";
    const useOpenAI = (() => {
      const provider = (cfg && cfg.LUMINA_LLM_PROVIDER) || "auto";
      return provider === "openai" || (provider === "auto" && cfg && cfg.OPENAI_API_KEY);
    })();
    name.textContent = useOpenAI ? ((cfg && cfg.OPENAI_MODEL) || "OpenAI 兼容模型") : m.name;
    const status = document.createElement("span");
    const hasKey = useOpenAI ? (cfg && cfg.OPENAI_API_KEY) : (cfg && cfg.DEEPSEEK_API_KEY);
    status.className = "m-status" + (hasKey ? "" : " err");
    status.textContent = hasKey
      ? (useOpenAI ? "已配置 OpenAI 兼容 Key" : "已配置 DeepSeek API Key")
      : "未配置 API Key，点击 ··· 配置";
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
  document.querySelectorAll("#modelOverlay input, #modelOverlay select").forEach(el => {
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

/* ---------- system notifications + sounds ---------- */
function playSound(kind){
  const opt = { agent: settings.sound_agent, permission: settings.sound_permission, error: settings.sound_error }[kind];
  if (!opt || opt === "none") return;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  try {
    const ctx = new AC();
    const notes = opt === "error"
      ? [[220, 0, 0.18], [170, 0.2, 0.28]]
      : opt === "chime"
        ? [[660, 0, 0.12], [990, 0.13, 0.2]]
        : [[520, 0, 0.1], [720, 0.11, 0.16]];
    notes.forEach(([freq, delay, dur]) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "sine"; o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, ctx.currentTime + delay);
      g.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + delay + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + delay + dur);
      o.connect(g); g.connect(ctx.destination);
      o.start(ctx.currentTime + delay); o.stop(ctx.currentTime + delay + dur + 0.05);
    });
  } catch (e) { /* audio unavailable */ }
}
function requestNotifPermission(){
  try { if ("Notification" in window && Notification.permission === "default") Notification.requestPermission(); } catch (e) {}
}
function notifyUser(title, body, kind){
  if (kind === "agent" && !settings.notif_agent) return;
  if (kind === "permission" && !settings.notif_permission) return;
  if (kind === "error" && !settings.notif_error) return;
  playSound(kind);
  try {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(title, { body: body || "", icon: "/static/assets/icon.ico" });
    }
  } catch (e) {}
}

/* ---------- keyboard shortcuts ---------- */
function isTypingTarget(t){
  return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
}
function cycleSession(delta){
  if (busy || !sessionsData.length) return;
  const idx = sessionsData.findIndex(s => s.id === currentSession);
  const n = sessionsData.length;
  const next = sessionsData[(idx < 0 ? -1 : idx) + delta + n] || sessionsData[(idx < 0 ? -1 : idx) + delta];
  if (next) switchSession(next.id);
}
document.addEventListener("keydown", (e) => {
  const t = e.target;
  if (e.key === "Escape") {
    const pal = document.getElementById("paletteOverlay");
    if (pal && !pal.hidden) { closePalette(); e.preventDefault(); return; }
    const term = document.getElementById("terminalbar");
    if (term && !term.hidden) { closeTerminal(); e.preventDefault(); return; }
    return;
  }
  if (!(e.ctrlKey || e.metaKey)) return;
  if (e.shiftKey && (e.key === "E" || e.key === "e")) {
    e.preventDefault(); input.focus(); return;
  }
  if (e.shiftKey && (e.key === "X" || e.key === "x")) {
    e.preventDefault(); toggleTerminal(); return;
  }
  if (e.shiftKey && (e.key === "O" || e.key === "o")) {
    e.preventDefault(); loadFileTree(); openPalette(); return;
  }
  const k = e.key.toLowerCase();
  if (k === ",") { e.preventDefault(); openSettings(); }
  else if (k === "t") {
    if (e.altKey) { e.preventDefault(); toggleTerminal(); }
    else if (!isTypingTarget(t)) { e.preventDefault(); newSession(); }
  }
  else if (k === "`") { e.preventDefault(); toggleTerminal(); }
  else if (k === "w") { e.preventDefault(); closeTerminal(); }
  else if (k === "k") { e.preventDefault(); togglePalette(); }
  else if (k === "[") { e.preventDefault(); cycleSession(-1); }
  else if (k === "]") { e.preventDefault(); cycleSession(1); }
});

/* ---------- terminal panel ---------- */
let termHist = [];
let termHistIdx = -1;
function termAppend(text, cls){
  const out = document.getElementById("termOut");
  if (!out) return;
  const line = document.createElement("div");
  line.className = "term-line" + (cls ? " " + cls : "");
  line.textContent = text;
  out.appendChild(line);
  out.scrollTop = out.scrollHeight;
}
function termSetStatus(text){
  const s = document.getElementById("termStatus");
  if (s) s.textContent = text || "";
}
function toggleTerminal(){
  const bar = document.getElementById("terminalbar");
  if (!bar) return;
  bar.hidden = !bar.hidden;
  if (!bar.hidden) {
    document.getElementById("termTitle").textContent = "终端 · " + (activeWorkspacePath || activeWorkspace || "");
    document.getElementById("termInput").focus();
  }
}
function closeTerminal(){
  const bar = document.getElementById("terminalbar");
  if (bar) bar.hidden = true;
}
function runTerminalCommand(cmd){
  if (!cmd) return;
  termAppend("❯ " + cmd, "cmd");
  termSetStatus("运行中…");
  ws.send(JSON.stringify({ type: "terminal", command: cmd }));
}
(function initTerminal(){
  const ti = document.getElementById("termInput");
  if (!ti) return;
  ti.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const cmd = ti.value.trim();
      if (!cmd) return;
      termHist.push(cmd); if (termHist.length > 50) termHist.shift();
      termHistIdx = termHist.length;
      ti.value = "";
      runTerminalCommand(cmd);
    } else if (e.key === "ArrowUp") {
      if (termHist.length && termHistIdx > 0) { termHistIdx--; ti.value = termHist[termHistIdx]; }
      e.preventDefault();
    } else if (e.key === "ArrowDown") {
      if (termHistIdx < termHist.length) { termHistIdx++; ti.value = termHistIdx < termHist.length ? termHist[termHistIdx] : ""; }
      e.preventDefault();
    }
  });
})();

/* ---------- file tree ---------- */
function showFileTreePanel(show){
  const sec = document.getElementById("fileTreeSec");
  if (sec) sec.style.display = show ? "" : "none";
  if (show) loadFileTree();
}
function loadFileTree(){
  const box = document.getElementById("fileTree");
  if (!box) return;
  box.innerHTML = '<p class="hint" style="margin:4px 0">加载中…</p>';
  fetch("/api/files?workspace=" + encodeURIComponent(activeWorkspace))
    .then(r => r.json())
    .then(data => {
      const cnt = document.getElementById("fileTreeCnt");
      if (cnt) cnt.textContent = data.count ? "· " + data.count : "";
      box.innerHTML = "";
      if (!data.tree || !data.tree.length) {
        box.innerHTML = '<p class="hint" style="margin:4px 0">（空目录）</p>';
        return;
      }
      renderFileTree(box, data.tree, 0);
    })
    .catch(() => { box.innerHTML = '<p class="hint" style="margin:4px 0">加载失败</p>'; });
}
function renderFileTree(box, nodes, depth){
  nodes.forEach(node => {
    const row = document.createElement("div");
    row.className = "ft-row" + (node.type === "dir" ? " ft-dir" : " ft-file");
    row.style.paddingLeft = (8 + depth * 14) + "px";
    const ic = document.createElement("span");
    ic.className = "ft-ic";
    ic.textContent = node.type === "dir" ? "▸" : "·";
    const nm = document.createElement("span");
    nm.className = "ft-name";
    nm.textContent = node.name;
    nm.title = node.path;
    row.appendChild(ic); row.appendChild(nm);
    if (node.type === "dir") {
      row.onclick = () => {
        const kids = row.querySelector(".ft-kids");
        if (kids) { row.classList.toggle("open"); kids.hidden = !kids.hidden; }
        else {
          const kids2 = document.createElement("div");
          kids2.className = "ft-kids";
          row.classList.add("open");
          renderFileTree(kids2, node.children || [], depth + 1);
          row.appendChild(kids2);
        }
      };
    } else {
      row.onclick = () => previewFile(node.path);
    }
    box.appendChild(row);
  });
}
function previewFile(path){
  fetch("/api/file?path=" + encodeURIComponent(path) + "&workspace=" + encodeURIComponent(activeWorkspace))
    .then(r => r.json())
    .then(data => {
      const bar = document.getElementById("terminalbar");
      if (bar) bar.hidden = false;
      document.getElementById("termTitle").textContent = "文件预览 · " + path;
      const out = document.getElementById("termOut");
      out.innerHTML = "";
      const head = document.createElement("div");
      head.className = "term-line head";
      head.textContent = "── " + path + (data.truncated ? "（截断）" : "") + " ──";
      out.appendChild(head);
      const body = document.createElement("div");
      body.className = "term-line body";
      body.textContent = data.content || "";
      out.appendChild(body);
      out.scrollTop = 0;
      termSetStatus("");
    })
    .catch(e => termAppend("预览失败: " + e.message, "err"));
}

/* ---------- @file reference popup ---------- */
let fileRefMatches = [];
let fileRefIdx = -1;
function fileRefFrag(text){
  const idx = text.lastIndexOf("@");
  if (idx < 0) return "";
  const prev = text[idx - 1];
  if (prev !== undefined && prev !== " " && prev !== "　" && prev !== "\n" && prev !== "@") return "";
  return text.slice(idx + 1).split(/\s/)[0] || "";
}
function fileRefFiles(node){
  const out = [];
  (node || []).forEach(n => {
    if (n.type === "file") out.push(n.path);
    else if (n.children) fileRefFiles(n.children).forEach(p => out.push(p));
  });
  return out;
}
function onFileRefInput(){
  const frag = fileRefFrag(input.value);
  const pop = document.getElementById("fileRefPop");
  if (!frag) { hideFileRefPop(); return; }
  fetch("/api/files?workspace=" + encodeURIComponent(activeWorkspace))
    .then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .then(data => {
      const all = fileRefFiles(data.tree || []);
      const q = frag.toLowerCase();
      const matches = all.filter(p => p.toLowerCase().indexOf(q) !== -1).slice(0, 8);
      if (!matches.length) { hideFileRefPop(); return; }
      fileRefMatches = matches;
      fileRefIdx = 0;
      pop.innerHTML = "";
      matches.forEach((p, i) => {
        const it = document.createElement("div");
        it.className = "fr-item" + (i === 0 ? " active" : "");
        it.textContent = p;
        it.onmousedown = (e) => { e.preventDefault(); insertFileRef(p); };
        pop.appendChild(it);
      });
      pop.hidden = false;
    })
    .catch(() => hideFileRefPop());
}
function paintFileRef(){
  const pop = document.getElementById("fileRefPop");
  if (!pop) return;
  [...pop.children].forEach((c, i) => c.classList.toggle("active", i === fileRefIdx));
}
function insertFileRef(path){
  const val = input.value;
  const idx = val.lastIndexOf("@");
  input.value = val.slice(0, idx + 1) + path + " ";
  hideFileRefPop();
  input.focus();
}
function hideFileRefPop(){
  const pop = document.getElementById("fileRefPop");
  if (pop) pop.hidden = true;
  fileRefMatches = [];
}

/* ---------- MCP + skills management ---------- */
let mcpServers = [];
function openMcpDialog(){
  document.getElementById("mcpDialogTitle").textContent = "添加 MCP 服务器";
  document.getElementById("mcp_name").value = "";
  document.getElementById("mcp_command").value = "";
  document.getElementById("mcp_args").value = "";
  document.getElementById("mcp_env").value = "";
  document.getElementById("mcpNote").textContent = "";
  document.getElementById("mcpOverlay").classList.add("open");
}
function closeMcpDialog(){ document.getElementById("mcpOverlay").classList.remove("open"); }
function saveMcpDialog(){
  const name = document.getElementById("mcp_name").value.trim();
  const command = document.getElementById("mcp_command").value.trim();
  const args = document.getElementById("mcp_args").value.split(",").map(s => s.trim()).filter(Boolean);
  const env = {};
  document.getElementById("mcp_env").value.split("\n").forEach(line => {
    const i = line.indexOf("=");
    if (i > 0) env[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  });
  if (!name || !command) { document.getElementById("mcpNote").textContent = "名称和命令不能为空"; return; }
  fetch("/api/mcp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "add", name, command, args, env }),
  }).then(r => r.json()).then(res => {
    if (res.ok) { closeMcpDialog(); renderMcp(); }
    else document.getElementById("mcpNote").textContent = "保存失败: " + (res.message || "");
  }).catch(() => { document.getElementById("mcpNote").textContent = "保存失败"; });
}
function renderMcp(){
  const list = document.getElementById("mcpList");
  const status = document.getElementById("mcpStatus");
  if (!list) return;
  list.innerHTML = "";
  fetch("/api/mcp").then(r => r.json()).then(data => {
    mcpServers = data.servers || {};
    if (status) {
      status.textContent = data.available
        ? "MCP 可用，配置文件：" + data.config_path
        : "MCP 依赖未安装（pip install lumina[mcp]）。配置仍可保存，但工具不会连接。";
      status.style.color = data.available ? "var(--muted)" : "var(--danger)";
    }
    const names = Object.keys(mcpServers);
    if (!names.length) {
      list.innerHTML = '<p class="hint" style="margin:0">尚未配置任何 MCP 服务器。</p>';
      return;
    }
    names.forEach(name => {
      const spec = mcpServers[name] || {};
      const row = document.createElement("div");
      row.className = "mcp-row";
      const info = document.createElement("div");
      info.className = "mcp-info";
      const nm = document.createElement("div"); nm.className = "mcp-name"; nm.textContent = name;
      const cmd = document.createElement("div"); cmd.className = "mcp-cmd";
      cmd.textContent = [spec.command, ...(spec.args || [])].filter(Boolean).join(" ") || "(无命令)";
      info.appendChild(nm); info.appendChild(cmd);
      const del = document.createElement("button");
      del.className = "danger"; del.textContent = "删除";
      del.onclick = () => {
        fetch("/api/mcp", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "remove", name }) })
          .then(r => r.json()).then(() => renderMcp());
      };
      row.appendChild(info); row.appendChild(del);
      list.appendChild(row);
    });
  }).catch(() => { list.innerHTML = '<p class="hint" style="margin:0">加载失败</p>'; });
}
function renderSkills(){
  const list = document.getElementById("skillList");
  if (!list) return;
  list.innerHTML = "";
  fetch("/api/skills?workspace=" + encodeURIComponent(activeWorkspace)).then(r => r.json()).then(data => {
    const skills = data.skills || [];
    if (!skills.length) {
      list.innerHTML = '<p class="hint" style="margin:0">未找到技能。可创建 <code>.lumina/skills/&lt;name&gt;/skill.md</code> 添加。</p>';
      return;
    }
    skills.forEach(s => {
      const row = document.createElement("div");
      row.className = "skill-row";
      const nm = document.createElement("div"); nm.className = "skill-name"; nm.textContent = s.name;
      if (s.triggers && s.triggers.length) {
        const tg = document.createElement("span"); tg.className = "skill-triggers";
        tg.textContent = "触发: " + s.triggers.join(" / ");
        nm.appendChild(tg);
      }
      const desc = document.createElement("div"); desc.className = "skill-desc";
      desc.textContent = s.description || "";
      const body = document.createElement("pre");
      body.className = "skill-body"; body.hidden = true;
      body.textContent = s.instructions || "";
      const view = document.createElement("button");
      view.textContent = "查看指令";
      view.onclick = () => { body.hidden = !body.hidden; view.textContent = body.hidden ? "查看指令" : "收起"; };
      row.appendChild(nm); row.appendChild(desc); row.appendChild(view); row.appendChild(body);
      list.appendChild(row);
    });
  }).catch(() => { list.innerHTML = '<p class="hint" style="margin:0">加载失败</p>'; });
}

/* ---------- command palette ---------- */
let paletteItems = [];
let paletteIdx = -1;
function paletteCommands(){
  return [
    { title: "新建会话", hint: "Ctrl+T", run: () => newSession() },
    { title: "切换工作区", hint: "", run: () => openWsManager() },
    { title: "打开设置", hint: "Ctrl+,", run: () => openSettings() },
    { title: "切换终端", hint: "Ctrl+`", run: () => toggleTerminal() },
    { title: "展开 / 收起侧边栏", hint: "", run: () => toggleSidebar() },
    { title: "刷新文件树", hint: "", run: () => { loadFileTree(); showFileTreePanel(true); } },
    { title: "检查更新", hint: "", run: () => checkUpdate() },
  ];
}
function togglePalette(){
  const pal = document.getElementById("paletteOverlay");
  if (!pal) return;
  if (pal.hidden) openPalette(); else closePalette();
}
function openPalette(){
  const pal = document.getElementById("paletteOverlay");
  if (!pal) return;
  pal.hidden = false;
  paletteItems = paletteCommands();
  renderPalette("");
  const pi = document.getElementById("paletteInput");
  pi.value = "";
  pi.focus();
  paletteIdx = -1;
}
function closePalette(){
  const pal = document.getElementById("paletteOverlay");
  if (pal) pal.hidden = true;
}
function renderPalette(q){
  const list = document.getElementById("paletteList");
  if (!list) return;
  const needle = q.toLowerCase();
  const items = paletteItems.filter(i => !needle || i.title.toLowerCase().includes(needle));
  list.innerHTML = "";
  items.forEach((it, i) => {
    const row = document.createElement("div");
    row.className = "palette-item" + (i === paletteIdx ? " active" : "");
    const t = document.createElement("span"); t.textContent = it.title;
    const h = document.createElement("span"); h.className = "palette-hint"; h.textContent = it.hint || "";
    row.appendChild(t); row.appendChild(h);
    row.onclick = () => { closePalette(); it.run(); };
    row.onmousemove = () => { paletteIdx = i; renderPalette(document.getElementById("paletteInput").value); };
    list.appendChild(row);
  });
}
(function initPalette(){
  const pi = document.getElementById("paletteInput");
  if (!pi) return;
  pi.addEventListener("input", () => { paletteIdx = -1; renderPalette(pi.value); });
  pi.addEventListener("keydown", (e) => {
    const list = document.getElementById("paletteList");
    const items = list ? list.querySelectorAll(".palette-item") : [];
    if (e.key === "ArrowDown") { paletteIdx = Math.min(paletteIdx + 1, items.length - 1); renderPalette(pi.value); e.preventDefault(); }
    else if (e.key === "ArrowUp") { paletteIdx = Math.max(paletteIdx - 1, 0); renderPalette(pi.value); e.preventDefault(); }
    else if (e.key === "Enter" && items[paletteIdx]) { const it = items[paletteIdx]; closePalette(); it.onclick(); }
  });
})();

loadSettings().then(() => refreshWorkspaces().then(() => connectWS(document.getElementById("wsSel").value || "")));
setTimeout(() => checkUpdate({ silent: true }), 4000);