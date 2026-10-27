/** 坐席工作台：转人工待办列表（黄金摘要）+ 标记完成 + 自动刷新。 */
import { completeHandover, fetchHandovers, type HandoverItem } from "./api";

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

function esc(text: string | null | undefined): string {
  return (text ?? "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

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

  if (!done) {
    const btn = document.createElement("button");
    btn.className = "done";
    btn.textContent = "处理完成";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await completeHandover(item.id);
        await load();
      } catch (err) {
        btn.disabled = false;
        showError(String(err));
      }
    });
    card.appendChild(btn);
  }
  return card;
}

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
// 自动刷新：坐席页保持最新待办
window.setInterval(() => void load(), 15000);
