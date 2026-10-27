/** 坐席工作台 V2.0：WebSocket 实时待办 + AI Copilot（工单卡片 / 快捷回复模板 / 内部系统查询）。 */
import {
  completeHandover,
  copilotQuery,
  fetchCopilot,
  fetchHandovers,
  generateTemplates,
  type CopilotTicket,
  type HandoverItem,
} from "./api";

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

function esc(text: string | null | undefined): string {
  return (text ?? "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ---------------- WebSocket 实时待办（失败自动降级 15s 轮询） ----------------

let ws: WebSocket | null = null;
let wsDegraded = false;

function wsUrl(): string {
  const proto = location.protocol === "https:" ? "wss://" : "ws://";
  return `${proto}${location.host}/ws/agent`;
}

function setWsState(on: boolean, text: string) {
  const el = $("ws-state");
  el.textContent = text;
  el.className = "ws-state " + (on ? "on" : "off");
}

function connectWs() {
  let sock: WebSocket;
  try {
    sock = new WebSocket(wsUrl());
  } catch {
    degrade();
    return;
  }
  ws = sock;
  sock.onopen = () => {
    wsDegraded = false;
    setWsState(true, "● 实时连接");
  };
  sock.onmessage = (msg) => {
    let data: { type?: string };
    try {
      data = JSON.parse(String(msg.data));
    } catch {
      return;
    }
    if (data.type === "handover_new" || data.type === "handover_done") void load();
  };
  sock.onerror = () => {
    if (sock) sock.close();
  };
  sock.onclose = () => {
    if (ws === sock && !wsDegraded) degrade();
  };
}

function degrade() {
  wsDegraded = true;
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
  setWsState(false, "已降级为 15s 轮询");
}

// ---------------- AI Copilot ----------------

function ticketRow(key: string, value: string | undefined): string {
  return `<div class="k">${key}</div><div class="v">${esc(value) || "—"}</div>`;
}

async function loadCopilot(card: HTMLElement, item: HandoverItem): Promise<void> {
  const area = document.createElement("div");
  area.className = "copilot";
  card.appendChild(area);

  const title = document.createElement("div");
  title.className = "copilot-title";
  title.textContent = "🤖 AI Copilot";
  area.appendChild(title);

  const loading = document.createElement("div");
  loading.className = "copilot-loading";
  loading.textContent = "生成工单卡片中…";
  area.appendChild(loading);

  let ticket: CopilotTicket = {};
  try {
    const res = await fetchCopilot(item.id);
    ticket = res.copilot?.ticket ?? {};
    loading.remove();
    const tk = document.createElement("div");
    tk.className = "ticket";
    tk.innerHTML =
      ticketRow("核心诉求", ticket.user_intent) +
      ticketRow("订单号/关键信息", ticket.order_info) +
      ticketRow("Bot 已解答", ticket.bot_answered) +
      ticketRow("未解决问题", ticket.issue);
    area.appendChild(tk);
    renderCopilotActions(area, item);
  } catch (err) {
    loading.textContent = "工单卡片加载失败：" + String(err);
  }
}

function renderCopilotActions(area: HTMLElement, item: HandoverItem): void {
  const btns = document.createElement("div");
  btns.className = "copilot-btns";

  const btnTpl = document.createElement("button");
  btnTpl.className = "primary";
  btnTpl.textContent = "✨ 生成回复模板";
  btnTpl.addEventListener("click", () => void genTemplates(area, item.id, btnTpl));

  const qLog = mkQueryBtn("查物流", "logistics", area, item);
  const qOrd = mkQueryBtn("查订单", "order", area, item);
  const qRef = mkQueryBtn("查退款", "refund", area, item);

  btns.append(btnTpl, qLog, qOrd, qRef);
  area.appendChild(btns);
}

function mkQueryBtn(
  label: string,
  action: "logistics" | "order" | "refund",
  area: HTMLElement,
  item: HandoverItem,
): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.textContent = label;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    void copilotQuery(item.id, action)
      .then((res) => {
        const box = document.createElement("div");
        box.className = "query-result";
        box.innerHTML =
          `<span class="mock-tag">开发期演示</span><b>${esc(res.action)}</b>：${esc(res.result)}`;
        area.querySelector(".query-result")?.remove();
        area.appendChild(box);
      })
      .catch((err) => {
        const box = document.createElement("div");
        box.className = "query-result";
        box.textContent = "查询失败：" + String(err);
        area.appendChild(box);
      })
      .finally(() => {
        btn.disabled = false;
      });
  });
  return btn;
}

async function genTemplates(area: HTMLElement, queueId: number, btn: HTMLButtonElement): Promise<void> {
  btn.disabled = true;
  btn.textContent = "生成中…";
  area.querySelector(".templates")?.remove();
  try {
    const res = await generateTemplates(queueId);
    const box = document.createElement("div");
    box.className = "templates";
    res.templates.forEach((tpl, i) => {
      const row = document.createElement("div");
      row.className = "template";
      row.textContent = `${i + 1}. ${tpl}`;
      const copy = document.createElement("button");
      copy.textContent = "复制";
      copy.addEventListener("click", () => {
        void navigator.clipboard.writeText(tpl).then(() => {
          copy.textContent = "已复制 ✓";
          window.setTimeout(() => {
            copy.textContent = "复制";
          }, 1500);
        });
      });
      row.appendChild(copy);
      box.appendChild(row);
    });
    area.appendChild(box);
  } catch (err) {
    const box = document.createElement("div");
    box.className = "query-result";
    box.textContent = "模板生成失败：" + String(err);
    area.appendChild(box);
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ 重新生成回复模板";
  }
}

// ---------------- 卡片渲染 ----------------

function renderCard(item: HandoverItem, done: boolean): HTMLDivElement {
  const card = document.createElement("div");
  card.className = done ? "card done-card" : "card";

  const badge = document.createElement("div");
  badge.className = "badge";
  badge.textContent = done ? "✓" : "#" + String(item.id);

  const body = document.createElement("div");
  body.className = "body";
  const summary = document.createElement("div");
  summary.className = "summary";
  summary.textContent = item.summary || "（无摘要）";
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.innerHTML =
    `<span>联系方式：<b>${esc(item.contact) || "未留"}</b></span>` +
    `<span>时间：<b>${esc(item.created_at)}</b></span>` +
    `<span>会话：<b>${esc(item.session_id.slice(0, 12))}…</b></span>`;
  body.append(summary, meta);
  card.append(badge, body);

  const actions = document.createElement("div");
  actions.style.cssText = "display:flex;flex-direction:column;gap:8px;align-items:flex-end;flex-shrink:0;";

  if (!done) {
    const btnCop = document.createElement("button");
    btnCop.className = "done";
    btnCop.style.background = "#7C3AED";
    btnCop.textContent = "🤖 AI Copilot";
    btnCop.addEventListener("click", () => {
      if (card.querySelector(".copilot")) return;
      btnCop.disabled = true;
      btnCop.textContent = "加载中…";
      void loadCopilot(card, item).finally(() => {
        btnCop.disabled = false;
        btnCop.textContent = "🤖 AI Copilot";
      });
    });

    const btnDone = document.createElement("button");
    btnDone.className = "done";
    btnDone.textContent = "处理完成";
    btnDone.addEventListener("click", async () => {
      btnDone.disabled = true;
      try {
        await completeHandover(item.id);
        await load();
      } catch (err) {
        btnDone.disabled = false;
        showError(String(err));
      }
    });
    actions.append(btnCop, btnDone);
  }
  card.appendChild(actions);
  return card;
}

// ---------------- 列表加载 ----------------

async function load(): Promise<void> {
  try {
    const [waiting, done] = await Promise.all([
      fetchHandovers("waiting"),
      fetchHandovers("done"),
    ]);
    $("st-waiting").textContent = String(waiting.length);
    $("st-done").textContent = String(done.length);
    $("st-total").textContent = String(waiting.length + done.length);
    $("waiting-cnt").textContent = String(waiting.length);
    $("done-cnt").textContent = String(done.length);

    const wl = $("waiting-list");
    wl.innerHTML = "";
    if (!waiting.length) {
      wl.innerHTML = '<div class="empty">🎉 暂无待办，所有转人工都已处理</div>';
    } else {
      waiting.forEach((it) => wl.appendChild(renderCard(it, false)));
    }

    const dl = $("done-list");
    dl.innerHTML = "";
    done.slice(0, 20).forEach((it) => dl.appendChild(renderCard(it, true)));
    showError("");
  } catch (err) {
    showError(String(err));
  }
}

function showError(text: string) {
  const el = $("error");
  el.className = "error";
  el.textContent = text;
}

$("refresh").addEventListener("click", () => void load());

void load();
connectWs();
// 降级保底：WS 断开时仍保持待办最新
window.setInterval(() => void load(), 15000);
