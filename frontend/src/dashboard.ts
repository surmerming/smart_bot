/** 运营看板：核心指标 + 比率条 + 会话漏斗 + 运行控制 + CSAT + Bad Case 管理（自动刷新）。 */
import {
  fetchBadCases,
  fetchCsat,
  fetchRuntime,
  fetchStats,
  setBadCaseStatus,
  updateRuntime,
  type OpsStats,
  type RuntimeState,
} from "./api";

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return (v * 100).toFixed(1) + "%";
}

function esc(text: string | null | undefined): string {
  return (text ?? "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ---------------- 核心指标 ----------------
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
    ["CSAT 平均分", s.csat_avg != null ? `⭐ ${s.csat_avg}` : "–", s.csat_total ? `${s.csat_total} 人打分` : "暂无打分"],
  ];
  for (const [label, num, sub, warn] of items) {
    const c = document.createElement("div");
    c.className = "card";
    c.innerHTML = `<div class="num ${warn ? "warn" : ""}">${num}</div><div class="label">${label} · ${sub}</div>`;
    cards.appendChild(c);
  }

  const bars = $("bars");
  bars.innerHTML = "";
  const rows: Array<[string, number, string]> = [
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

// ---------------- 运行控制（Kill Switch + 灰度） ----------------
const MODE_LABEL: Record<string, { zh: string; desc: string; cls: string }> = {
  auto: { zh: "正常服务", desc: "RAG + 自动回答 + 转人工决策全开", cls: "" },
  handover: { zh: "全局转人工", desc: "半切：所有对话直接登记人工，不调 LLM", cls: "warn" },
  off: { zh: "维护下线", desc: "全切：统一回复维护话术，不登记不入队", cls: "warn" },
};

function renderRuntime(st: RuntimeState): void {
  for (const btn of document.querySelectorAll<HTMLButtonElement>("#rc-modes .rc-btn")) {
    const on = btn.dataset.mode === st.mode;
    btn.classList.toggle("active", on);
  }
  const slider = $<HTMLInputElement>("rc-gray");
  slider.value = String(st.gray_percent);
  $("rc-gray-val").textContent = `${st.gray_percent}%`;
  const info = MODE_LABEL[st.mode];
  const stEl = $("rc-status");
  stEl.className = `rc-status ${info.cls}`;
  const grayNote =
    st.gray_percent > 0 && st.gray_percent < 100
      ? ` · 灰度放量 ${st.gray_percent}%（按会话哈希分流，命中组 gray=true）`
      : st.gray_percent >= 100
        ? " · 灰度 100%（全量放行）"
        : "";
  stEl.textContent = `当前模式：${info.zh}（${info.desc}）${grayNote}`;
}

async function loadRuntime(): Promise<void> {
  try {
    renderRuntime(await fetchRuntime());
  } catch (err) {
    $("rc-status").className = "rc-status warn";
    $("rc-status").textContent = `运行控制读取失败：${String(err)}`;
  }
}

$("rc-modes").addEventListener("click", (ev) => {
  const btn = (ev.target as HTMLElement).closest<HTMLButtonElement>(".rc-btn");
  if (!btn) return;
  const mode = btn.dataset.mode as RuntimeState["mode"];
  void updateRuntime({ mode })
    .then(renderRuntime)
    .catch((err) => {
      $("rc-status").className = "rc-status warn";
      $("rc-status").textContent = `切换失败：${String(err)}`;
    });
});

let grayTimer = 0;
$("rc-gray").addEventListener("input", (ev) => {
  const v = (ev.target as HTMLInputElement).value;
  $("rc-gray-val").textContent = `${v}%`;
  window.clearTimeout(grayTimer);
  grayTimer = window.setTimeout(() => {
    void updateRuntime({ gray_percent: Number(v) })
      .then(renderRuntime)
      .catch((err) => {
        $("rc-status").className = "rc-status warn";
        $("rc-status").textContent = `灰度设置失败：${String(err)}`;
      });
  }, 400);
});

// ---------------- CSAT 满意度 ----------------
async function renderCsat(): Promise<void> {
  const el = $("csat");
  try {
    const s = await fetchCsat();
    if (!s.csat_total) {
      el.innerHTML = `<div class="tip">暂无满意度数据 —— Widget 在转人工后弹出 1-5 星打分。</div>`;
      return;
    }
    let html = `<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:14px">` +
      `<span style="font-size:34px;font-weight:700;color:#0066CC">${s.csat_avg}</span>` +
      `<span class="star">★★★★★</span>` +
      `<span style="font-size:12px;color:#6B7280">平均分 · 共 ${s.csat_total} 人打分</span></div>` +
      `<div class="csat-bars">`;
    const max = Math.max(1, ...Object.values(s.csat_dist));
    for (let r = 5; r >= 1; r--) {
      const cnt = s.csat_dist[String(r)] ?? 0;
      html += `<div class="crow"><div class="cname">${r} 星</div>` +
        `<div class="cbar"><i style="width:${(cnt / max) * 100}%"></i></div>` +
        `<div class="cnum">${cnt}</div></div>`;
    }
    html += `</div>`;
    el.innerHTML = html;
  } catch (err) {
    el.innerHTML = `<div class="error">${esc(String(err))}</div>`;
  }
}

// ---------------- Bad Case 管理 ----------------
const BAD_STATUS_ZH: Record<string, string> = { open: "待处理", resolved: "已处理", ignored: "已忽略" };

async function setStatus(fid: number, status: "resolved" | "ignored"): Promise<void> {
  let note = "";
  if (status === "resolved") {
    note = window.prompt("处理备注（可选，建议填写：改了什么知识库/怎么修的）：", "") ?? "";
  }
  try {
    await setBadCaseStatus(fid, status, note);
    await renderBadCases();
  } catch (err) {
    window.alert(`标记失败：${String(err)}`);
  }
}

async function renderBadCases(): Promise<void> {
  const tbody = $("badcases");
  tbody.innerHTML = "";
  try {
    const cases = await fetchBadCases(15);
    if (!cases.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">暂无点踩记录，说明当前回答质量不错 🎉</td></tr>';
      return;
    }
    for (const c of cases) {
      const st = (c.status ?? "open") as string;
      const note = c.note ? `<div class="tip" style="margin-top:4px">📝 ${esc(c.note)}</div>` : "";
      const op = st === "open"
        ? `<button class="mini-btn" data-fid="${c.id}" data-act="resolved">标记已处理</button>` +
          `<button class="mini-btn" data-fid="${c.id}" data-act="ignored">忽略</button>`
        : "";
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td class="q">${esc(c.query)}</td>` +
        `<td class="a">${esc((c.answer ?? "").slice(0, 120))}</td>` +
        `<td>${esc(c.created_at)}</td>` +
        `<td><span class="badge ${st}">${BAD_STATUS_ZH[st] ?? st}</span>${note}` +
        `<div style="margin-top:6px">${op}</div></td>`;
      tbody.appendChild(tr);
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="error">${esc(String(err))}</td></tr>`;
  }
}

$("badcases").addEventListener("click", (ev) => {
  const btn = (ev.target as HTMLElement).closest<HTMLButtonElement>(".mini-btn");
  if (!btn) return;
  const fid = Number(btn.dataset.fid);
  const act = btn.dataset.act as "resolved" | "ignored";
  void setStatus(fid, act);
});

// ---------------- 主加载 ----------------
async function load(): Promise<void> {
  try {
    const s = await fetchStats();
    renderStats(s);
    $("error").textContent = "";
  } catch (err) {
    $("error").textContent = String(err);
  }
}

$("refresh").addEventListener("click", () => {
  void load();
  void loadRuntime();
  void renderCsat();
  void renderBadCases();
});
void load();
void loadRuntime();
void renderCsat();
void renderBadCases();
window.setInterval(() => {
  void load();
  void loadRuntime();
  void renderCsat();
  void renderBadCases();
}, 15000);
