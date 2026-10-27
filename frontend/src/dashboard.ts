/** 运营看板：核心指标 + 比率条 + 会话漏斗 + Bad Case 列表（自动刷新）。 */
import { fetchBadCases, fetchStats, type OpsStats } from "./api";

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return (v * 100).toFixed(1) + "%";
}

function renderStats(s: OpsStats): void {
  const cards = $("cards");
  cards.innerHTML = "";
  const items: Array<[string, string, string, boolean?]> = [
    ["总咨询量", String(s.total_sessions), "所有发起的新会话"],
    ["纯 Agent 解决", String(s.agent_resolved), "全程未触发转人工"],
    ["转人工量", String(s.handover), "会话中曾触发转人工", true],
    ["自动化率", pct(s.auto_rate), "Agent 闭环占比"],
    ["转人工率", pct(s.handover_rate), "= 1 − 自动化率"],
    ["点赞率", pct(s.up_rate), s.feedback_total ? `👍 ${s.feedback_up} / 👎 ${s.feedback_down}` : "暂无反馈"],
  ];
  for (const [label, num, sub, warn] of items) {
    const c = document.createElement("div");
    c.className = "card";
    c.innerHTML = `<div class="num ${warn ? "warn" : ""}">${num}</div><div class="label">${label} · ${sub}</div>`;
    cards.appendChild(c);
  }

  const bars = $("bars");
  bars.innerHTML = "";
  const rows: Array<[string, number, string, boolean?]> = [
    ["自动化率", s.auto_rate, "#0066CC"],
    ["转人工率", s.handover_rate, "#F59E0B"],
    ["点赞率", s.up_rate ?? 0, "#22C55E"],
  ];
  for (const [name, val, color] of rows) {
    const row = document.createElement("div");
    row.className = "bar-row";
    const w = Math.min(Math.max(val * 100, 0), 100);
    row.innerHTML =
      `<div class="name">${name}</div>` +
      `<div class="bar"><i style="width:${w}%;background:${color}"></i></div>` +
      `<div class="val">${pct(val)}</div>`;
    bars.appendChild(row);
  }

  const funnel = $("funnel");
  funnel.innerHTML = "";
  const total = s.total_sessions || 1;
  const a = s.agent_resolved;
  const bc = s.handover;
  const max = Math.max(a, bc, 1);
  const cols: Array<[string, number, string, string]> = [
    ["State A · 纯 Agent 闭环", a, "auto", String(a)],
    ["State B+C · 转人工", bc, "orange", String(bc)],
    ["总咨询量", total, "blue", String(total)],
  ];
  for (const [label, val, cls, num] of cols) {
    const col = document.createElement("div");
    col.className = "col";
    const h = Math.max((val / max) * 100, val > 0 ? 6 : 0);
    col.innerHTML =
      `<div class="bar"><i class="${cls}" style="height:${h}%"></i></div>` +
      `<div class="num">${num}</div><div class="label">${label}</div>`;
    funnel.appendChild(col);
  }
}

function esc(text: string | null | undefined): string {
  return (text ?? "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function renderBadCases(): Promise<void> {
  const tbody = $("badcases");
  tbody.innerHTML = "";
  try {
    const cases = await fetchBadCases(15);
    if (!cases.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty">暂无点踩记录，说明当前回答质量不错 🎉</td></tr>';
      return;
    }
    for (const c of cases) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td class="q">${esc(c.query)}</td>` +
        `<td class="a">${esc((c.answer ?? "").slice(0, 120))}</td>` +
        `<td>${esc(c.created_at)}</td>`;
      tbody.appendChild(tr);
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="3" class="error">${esc(String(err))}</td></tr>`;
  }
}

async function load(): Promise<void> {
  try {
    const s = await fetchStats();
    renderStats(s);
    $("error").textContent = "";
  } catch (err) {
    $("error").textContent = String(err);
  }
}

$("refresh").addEventListener("click", () => void load());
void load();
void renderBadCases();
window.setInterval(() => {
  void load();
  void renderBadCases();
}, 15000);
