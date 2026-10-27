/** 聊天 Widget Web Component：<xd-chat-widget>。
 *
 * 两种形态（attribute `mode`）：
 *   - inline  内嵌面板（官网 Hero 演示区使用）
 *   - floating 右下角悬浮按钮 + 弹出面板（嵌入任意官网）
 *
 * 附加属性：
 *   - api-base  后端地址（缺省同源，走 /api 代理）
 *   - brand     品牌名（缺省取后端 init 返回）
 */
import { chatInit, fetchQueueStatus, manualHandover, sendFeedback } from "./api";
import { postSSE } from "./sse-client";

const STORE_KEY = "xd_anonymous_session_id";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  query?: string;
  messageId?: string;
  faqIds?: string[];
  handover?: boolean;
  tipEl?: HTMLElement;
}

const WIDGET_CSS = `
:host { all: initial; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; }
.xd-fab {
  position: fixed; right: 24px; bottom: 24px; z-index: 9999;
  width: 56px; height: 56px; border-radius: 50%;
  background: #0066CC; color: #fff; border: none; cursor: pointer;
  box-shadow: 0 8px 24px rgba(0,102,204,.35); display: flex; align-items: center; justify-content: center;
  transition: transform .2s ease;
}
.xd-fab:hover { transform: scale(1.06); }
.xd-fab svg { width: 28px; height: 28px; }
.xd-badge {
  position: absolute; top: -2px; right: -2px; min-width: 18px; height: 18px; padding: 0 4px;
  background: #EF4444; color: #fff; font-size: 11px; border-radius: 9px; display: flex; align-items: center; justify-content: center;
  box-sizing: border-box;
}
.xd-panel {
  width: 360px; max-width: calc(100vw - 32px); height: 560px; max-height: calc(100vh - 120px);
  display: flex; flex-direction: column; border-radius: 16px; overflow: hidden;
  background: #fff; box-shadow: 0 12px 48px rgba(17,18,20,.16); border: 1px solid #ECECEF;
  position: fixed; right: 24px; bottom: 92px; z-index: 9998;
}
.xd-panel.inline {
  position: relative; right: auto; bottom: auto; z-index: 0;
  box-shadow: 0 8px 32px rgba(17,18,20,.10); height: 480px;
}
.xd-header {
  display: flex; align-items: center; gap: 8px; padding: 14px 16px;
  background: #FAFAFC; border-bottom: 1px solid #ECECEF;
}
.xd-header-logo {
  width: 32px; height: 32px; border-radius: 9px; background: #0066CC; color: #fff;
  display: flex; align-items: center; justify-content: center; font-size: 15px; font-weight: 700; flex-shrink: 0;
}
.xd-header-title { font-size: 14px; font-weight: 600; color: #111214; line-height: 1.2; }
.xd-header-status { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #6B7280; margin-top: 2px; }
.xd-dot { width: 6px; height: 6px; border-radius: 50%; background: #22C55E; }
.xd-close { margin-left: auto; background: none; border: none; cursor: pointer; color: #6B7280; font-size: 18px; padding: 2px 6px; }
.xd-close:hover { color: #111214; }
.xd-messages { flex: 1; overflow-y: auto; padding: 16px; background: #FAFAFC; display: flex; flex-direction: column; gap: 12px; }
.xd-msg { display: flex; flex-direction: column; max-width: 84%; }
.xd-msg.bot { align-self: flex-start; align-items: flex-start; }
.xd-msg.user { align-self: flex-end; align-items: flex-end; }
.xd-bubble {
  padding: 10px 13px; border-radius: 12px; font-size: 14px; line-height: 1.55; white-space: pre-wrap; word-break: break-word;
}
.xd-msg.bot .xd-bubble { background: #fff; border: 1px solid #ECECEF; color: #111214; border-top-left-radius: 4px; }
.xd-msg.user .xd-bubble { background: #0066CC; color: #fff; border-top-right-radius: 4px; }
.xd-faq-badge {
  margin-top: 6px; font-size: 11px; color: #16A34A; background: #F0FDF4; border: 1px solid #BBF7D0;
  padding: 3px 8px; border-radius: 8px; display: inline-flex; align-items: center; gap: 4px;
}
.xd-feedback { margin-top: 6px; font-size: 12px; color: #9CA3AF; display: flex; align-items: center; gap: 4px; }
.xd-feedback button { background: none; border: none; cursor: pointer; font-size: 13px; padding: 0 3px; color: #6B7280; }
.xd-feedback button:hover { color: #111214; }
.xd-handover-tip {
  margin: 6px 0 0; padding: 8px 10px; background: #FFF7ED; border: 1px solid #FED7AA; color: #9A3412;
  border-radius: 10px; font-size: 12px; line-height: 1.5;
}
.xd-typing { display: inline-flex; gap: 4px; padding: 4px 0; }
.xd-typing span { width: 6px; height: 6px; border-radius: 50%; background: #C4C4CC; animation: xd-bounce 1.2s infinite; }
.xd-typing span:nth-child(2) { animation-delay: .2s; }
.xd-typing span:nth-child(3) { animation-delay: .4s; }
@keyframes xd-bounce { 0%,60%,100%{transform:translateY(0);opacity:.4} 30%{transform:translateY(-4px);opacity:1} }
.xd-chips { padding: 8px 16px 0; background: #FAFAFC; display: flex; flex-wrap: wrap; gap: 8px; }
.xd-chip {
  background: #fff; border: 1px solid #BBD7F2; color: #0066CC; border-radius: 14px;
  font-size: 12px; padding: 6px 11px; cursor: pointer; transition: all .15s;
}
.xd-chip:hover { background: #0066CC; color: #fff; }
.xd-input-bar { display: flex; gap: 8px; padding: 12px 16px; background: #fff; border-top: 1px solid #ECECEF; }
.xd-input-bar input {
  flex: 1; border: none; outline: none; background: #F5F5F7; border-radius: 10px;
  padding: 10px 14px; font-size: 14px; color: #111214;
}
.xd-input-bar button {
  border: none; background: #0066CC; color: #fff; border-radius: 10px; padding: 0 18px;
  font-size: 14px; cursor: pointer; font-weight: 600;
}
.xd-input-bar button:disabled { background: #A8C8EA; cursor: not-allowed; }
.xd-error { text-align: center; color: #EF4444; font-size: 12px; padding: 8px 12px; }
`;

export class ChatWidget extends HTMLElement {
  private mode: "floating" | "inline" = "floating";
  private apiBase = "";
  private brand = "小答";
  private sessionId = "";
  private visitorToken = "";
  private quickChips: { label: string; value: string }[] = [];
  private messages: ChatMsg[] = [];
  private streaming = false;
  private unread = 0;
  private initialized = false;
  private panelOpen = false;
  private queueTipEl: HTMLElement | null = null;
  private queueTimer: number | null = null;
  private queueWs: WebSocket | null = null;

  private shadow = this.attachShadow({ mode: "open" });
  private elFab!: HTMLElement;
  private elPanel!: HTMLElement;
  private elMessages!: HTMLElement;
  private elInput!: HTMLInputElement;
  private elSend!: HTMLButtonElement;
  private elChips!: HTMLElement;
  private elBadge!: HTMLElement;

  static get observedAttributes() {
    return ["mode", "api-base", "brand"];
  }

  attributeChangedCallback(name: string, _old: string, value: string) {
    if (name === "mode") this.mode = value === "inline" ? "inline" : "floating";
    if (name === "api-base") this.apiBase = value.replace(/\/$/, "");
    if (name === "brand") this.brand = value || "小答";
  }

  connectedCallback() {
    this.render();
    if (this.mode === "inline") {
      this.panelOpen = true;
      this.elPanel.classList.add("inline");
      this.elPanel.style.display = "flex";
      void this.init();
    } else {
      this.elPanel.style.display = "none";
    }
    this.elFab.addEventListener("click", () => this.togglePanel());
    this.elPanel.querySelector(".xd-close")?.addEventListener("click", () => this.togglePanel(false));
    this.elSend.addEventListener("click", () => void this.send());
    this.elInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void this.send();
      }
    });
  }

  // ---------------- 渲染 ----------------
  private render() {
    this.shadow.innerHTML = `
      <style>${WIDGET_CSS}</style>
      <button class="xd-fab" title="打开小答客服">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
        </svg>
        <span class="xd-badge" style="display:none">0</span>
      </button>
      <div class="xd-panel">
        <div class="xd-header">
          <div class="xd-header-logo">答</div>
          <div>
            <div class="xd-header-title">小答 · AI客服</div>
            <div class="xd-header-status"><span class="xd-dot"></span>在线 · 通常秒回</div>
          </div>
          <button class="xd-close" aria-label="关闭">×</button>
        </div>
        <div class="xd-messages"></div>
        <div class="xd-chips"></div>
        <form class="xd-input-bar" onsubmit="event.preventDefault()">
          <input placeholder="输入你的问题…" autocomplete="off" />
          <button type="submit">发送</button>
        </form>
      </div>
    `;
    this.elFab = this.shadow.querySelector(".xd-fab")!;
    this.elBadge = this.shadow.querySelector(".xd-badge")!;
    this.elPanel = this.shadow.querySelector(".xd-panel")!;
    this.elMessages = this.shadow.querySelector(".xd-messages")!;
    this.elChips = this.shadow.querySelector(".xd-chips")!;
    this.elInput = this.shadow.querySelector("input")!;
    this.elSend = this.shadow.querySelector(".xd-input-bar button")!;
  }

  private togglePanel(force?: boolean) {
    const open = force ?? !this.panelOpen;
    this.panelOpen = open;
    this.elPanel.style.display = open ? "flex" : "none";
    if (open) {
      this.elBadge.style.display = "none";
      this.unread = 0;
      if (!this.initialized) void this.init();
      else void this.renderHistory();
      setTimeout(() => this.elInput.focus(), 50);
    }
  }

  // ---------------- 初始化 ----------------
  private async init() {
    this.initialized = true;
    try {
      const stored = localStorage.getItem(STORE_KEY) || undefined;
      const res = await chatInit({ session_id: stored });
      localStorage.setItem(STORE_KEY, res.session_id);
      this.sessionId = res.session_id;
      this.visitorToken = res.visitor_token;
      this.brand = res.brand_name || this.brand;
      this.quickChips = res.quick_chips || [];
      this.messages = (res.history || []).map((m) => ({ role: m.role, content: m.content }));
      if (!this.messages.length) {
        this.messages.push({ role: "assistant", content: `你好，我是${this.brand}(AI客服)～有什么可以帮你的？` });
        // inline 演示区：补一条静态演示对话（1:1 对齐设计稿 s_hero.png）
        if (this.mode === "inline") {
          this.messages.push(
            { role: "user", content: "拆了包装还能退吗？" },
            {
              role: "assistant",
              content: "支持7天无理由退换～拆封试用不影响，只要包装配件齐全就行，放心冲！",
              faqIds: ["FAQ_001 · 退换货政策 · 相似度 0.91"],
            },
          );
        }
      }
      await this.renderHistory();
      this.renderChips(this.quickChips);
    } catch (err) {
      this.pushError("连不上客服服务，请确认后端已启动");
      console.error("[xd-chat] init failed:", err);
    }
  }

  // ---------------- 消息渲染 ----------------
  private renderHistory() {
    this.elMessages.innerHTML = "";
    for (const msg of this.messages) this.appendMessageEl(msg);
    this.scrollBottom();
  }

  private appendMessageEl(msg: ChatMsg) {
    const row = document.createElement("div");
    row.className = `xd-msg ${msg.role === "user" ? "user" : "bot"}`;

    const bubble = document.createElement("div");
    bubble.className = "xd-bubble";
    bubble.textContent = msg.content;
    row.appendChild(bubble);

    if (msg.role === "assistant") {
      // 命中知识库徽章（设计稿 F1：命中 FAQ_001 · 退换货政策 · 相似度 0.91）
      if (msg.faqIds?.length) {
        const badge = document.createElement("div");
        badge.className = "xd-faq-badge";
        badge.textContent = msg.faqIds.length === 1 && msg.faqIds[0].includes("·")
          ? `命中 ${msg.faqIds[0]}`
          : `命中 ${msg.faqIds.join(" · ")} · 知识库`;
        row.appendChild(badge);
      }
      if (msg.handover) {
        const tip = document.createElement("div");
        tip.className = "xd-handover-tip";
        tip.textContent = "已转人工排队（留言模式）：客服上线后第一时间回复，排队期间可继续咨询其他问题。";
        row.appendChild(tip);
      }
      // 反馈按钮（👍 没问题 / 👎 没解决）
      const fb = document.createElement("div");
      fb.className = "xd-feedback";
      fb.innerHTML = `<span>这个回答有帮助吗？</span>
        <button data-v="up" title="没问题">👍</button>
        <button data-v="down" title="没解决">👎</button>`;
      fb.querySelectorAll("button").forEach((btn) =>
        btn.addEventListener("click", () => this.submitFeedback(msg, btn.dataset.v as "up" | "down")),
      );
      row.appendChild(fb);
    }

    this.elMessages.appendChild(row);
    this.scrollBottom();
  }

  private scrollBottom() {
    this.elMessages.scrollTop = this.elMessages.scrollHeight;
  }

  private pushError(text: string) {
    const div = document.createElement("div");
    div.className = "xd-error";
    div.textContent = text;
    this.elMessages.appendChild(div);
  }

  private renderChips(chips: { label: string; value: string }[]) {
    this.elChips.innerHTML = "";
    for (const chip of chips) {
      const btn = document.createElement("button");
      btn.className = "xd-chip";
      btn.textContent = chip.label;
      btn.addEventListener("click", () => void this.send(chip.value));
      this.elChips.appendChild(btn);
    }
  }

  // ---------------- 发送与流式 ----------------
  private async send(text?: string) {
    const content = (text ?? this.elInput.value).trim();
    if (!content || this.streaming) return;
    this.elInput.value = "";
    this.elChips.innerHTML = "";

    // 用户气泡
    this.messages.push({ role: "user", content });
    this.appendMessageEl({ role: "user", content });

    // Bot 占位 + typing
    const botMsg: ChatMsg = { role: "assistant", content: "" };
    this.messages.push(botMsg);
    const row = document.createElement("div");
    row.className = "xd-msg bot";
    row.innerHTML = `<div class="xd-bubble"><span class="xd-typing"><span></span><span></span><span></span></span></div>`;
    this.elMessages.appendChild(row);
    this.scrollBottom();

    this.streaming = true;
    this.elSend.disabled = true;
    let lastMeta: Record<string, unknown> = {};

    try {
      await postSSE(
        `${this.apiBase}/api/v1/chat/stream`,
        { session_id: this.sessionId, visitor_token: this.visitorToken, message: content },
        (ev) => {
          if (ev.event === "meta") lastMeta = ev.data;
          if (ev.event === "text") {
            const chunk = String(ev.data.content ?? "");
            botMsg.content += chunk;
            this.updateBubble(row, botMsg.content, true);
          }
          if (ev.event === "done") {
            botMsg.messageId = String(ev.data.message_id ?? "");
            botMsg.handover = Boolean(ev.data.handover);
          }
          // V1.5+：转人工后拿 queue_id → V2.0 优先 WebSocket 实时排队，失败降级轮询
          if (ev.event === "summary") {
            const qid = ev.data.queue_id;
            if (typeof qid === "number" && qid > 0) this.startQueueLive(qid);
          }
        },
      );
    } catch (err) {
      botMsg.content = "网络开小差了，请稍后再试～";
      this.updateBubble(row, botMsg.content, false);
      console.error("[xd-chat] stream failed:", err);
    }

    // 完成态：替换 typing，绑定徽章/反馈/转人工提示
    if (botMsg.content) {
      row.innerHTML = "";
      const bubble = document.createElement("div");
      bubble.className = "xd-bubble";
      bubble.textContent = botMsg.content;
      row.appendChild(bubble);
      const faqs = (lastMeta.faqs as { id: string; title: string; score: number }[]) || [];
      const faqIds = (lastMeta.faq_ids as string[]) || [];
      if (faqs.length) {
        botMsg.faqIds = [`${faqs[0].id} · ${faqs[0].title} · 相似度 ${faqs[0].score.toFixed(2)}`];
        const badge = document.createElement("div");
        badge.className = "xd-faq-badge";
        badge.textContent = `命中 ${botMsg.faqIds[0]}`;
        row.appendChild(badge);
      } else if (faqIds.length) {
        botMsg.faqIds = faqIds;
        const badge = document.createElement("div");
        badge.className = "xd-faq-badge";
        badge.textContent = `命中 ${faqIds.join(" · ")} · 知识库`;
        row.appendChild(badge);
      }
      if (botMsg.handover) {
        const tip = document.createElement("div");
        tip.className = "xd-handover-tip";
        tip.textContent = "已转人工排队（留言模式）：客服上线后第一时间回复，排队期间可继续咨询其他问题。";
        row.appendChild(tip);
        botMsg.tipEl = tip;
        this.queueTipEl = tip;
      }
      const fb = document.createElement("div");
      fb.className = "xd-feedback";
      fb.innerHTML = `<span>这个回答有帮助吗？</span><button data-v="up" title="没问题">👍</button><button data-v="down" title="没解决">👎</button>`;
      fb.querySelectorAll("button").forEach((btn) =>
        btn.addEventListener("click", () => this.submitFeedback(botMsg, btn.dataset.v as "up" | "down")),
      );
      row.appendChild(fb);
      botMsg.query = content;
    }

    // 快捷按钮：软转人工 / 排队期间继续咨询
    const quickReplies = (lastMeta.quick_replies as { label: string; value: string }[]) || [];
    if (quickReplies.length) this.renderChips(quickReplies);

    // floating 模式：面板关闭时累计未读
    if (!this.panelOpen && this.unread >= 0) {
      this.unread += 1;
      this.elBadge.style.display = "flex";
      this.elBadge.textContent = String(this.unread);
    }

    this.streaming = false;
    this.elSend.disabled = false;
    this.scrollBottom();
  }

  private updateBubble(row: HTMLElement, text: string, typing: boolean) {
    const bubble = row.querySelector(".xd-bubble")!;
    if (typing) {
      bubble.innerHTML = `${text.replace(/</g, "&lt;")}<span class="xd-caret" style="display:inline-block;width:2px;height:14px;background:#0066CC;margin-left:2px;vertical-align:-2px;animation:xd-blink 1s infinite"></span>`;
    } else {
      bubble.textContent = text;
    }
    this.scrollBottom();
  }

  // ---------------- 反馈 & 转人工 ----------------
  private async submitFeedback(msg: ChatMsg, value: "up" | "down") {
    try {
      await sendFeedback({
        session_id: this.sessionId,
        message_id: msg.messageId || undefined,
        value,
        query: msg.query,
        answer: msg.content,
      });
    } catch (err) {
      console.error("[xd-chat] feedback failed:", err);
    }
  }

  public async requestHandover(contact?: string) {
    try {
      const res = await manualHandover({
        session_id: this.sessionId,
        visitor_token: this.visitorToken,
        contact,
      });
      if (res.ok) this.pushError(res.message || "已登记转人工");
    } catch (err) {
      console.error("[xd-chat] handover failed:", err);
    }
  }

  // ---------------- V2.0 排队进度：WebSocket 实时（失败自动降级 V1.5 轮询） ----------------
  private wsUrl(path: string): string {
    if (this.apiBase) {
      return `${this.apiBase.replace(/^http/, "ws")}${path}`;
    }
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    return `${proto}${location.host}${path}`;
  }

  private startQueueLive(queueId: number) {
    this.stopQueueLive();
    this.stopQueuePolling();
    let ws: WebSocket;
    try {
      ws = new WebSocket(
        this.wsUrl(
          `/ws/user?session_id=${encodeURIComponent(this.sessionId)}&visitor_token=${encodeURIComponent(this.visitorToken)}`,
        ),
      );
    } catch {
      this.startQueuePolling(queueId);
      return;
    }
    this.queueWs = ws;
    ws.onmessage = (msg) => {
      let data: { type?: string; queue_id?: number; position?: number | null; ahead?: number | null; status?: string };
      try {
        data = JSON.parse(String(msg.data));
      } catch {
        return;
      }
      const tip = this.queueTipEl;
      if (!tip) return;
      if (data.type === "queue") {
        if (data.status === "waiting") {
          tip.textContent =
            data.position && data.position > 0
              ? `已转人工排队：前面还有 ${data.ahead ?? 0} 人，客服上线后第一时间回复，排队期间可继续咨询其他问题。`
              : "已转人工排队：客服上线后第一时间回复，排队期间可继续咨询其他问题。";
        } else if (data.status === "done") {
          tip.textContent = "人工客服已接入，正在为您服务。";
          this.stopQueueLive();
        }
      } else if (data.type === "agent_joined") {
        tip.textContent = "人工客服已接入，正在为您服务。";
        this.stopQueueLive();
      }
    };
    ws.onerror = () => this.fallbackPolling(queueId);
    ws.onclose = () => this.fallbackPolling(queueId);
  }

  private fallbackPolling(queueId: number) {
    // stopQueueLive 主动关闭会先把 onclose 置空，不会走到这里；走到这里说明连接确实断了 → 降级轮询
    if (this.queueWs === null) return;
    this.queueWs = null;
    this.startQueuePolling(queueId);
  }

  private stopQueueLive() {
    if (this.queueWs !== null) {
      const ws = this.queueWs;
      this.queueWs = null;
      ws.onclose = null;
      ws.close();
    }
  }

  // ---------------- V1.5 排队进度轮询（WebSocket 不可用时的降级） ----------------
  private startQueuePolling(queueId: number) {
    this.stopQueuePolling();
    this.stopQueueLive();
    const poll = async () => {
      try {
        const st = await fetchQueueStatus(queueId);
        const tip = this.queueTipEl;
        if (tip) {
          if (st.status === "waiting") {
            tip.textContent = st.position
              ? `已转人工排队：前面还有 ${st.ahead ?? 0} 人，客服上线后第一时间回复，排队期间可继续咨询其他问题。`
              : "已转人工排队：客服上线后第一时间回复，排队期间可继续咨询其他问题。";
          } else if (st.status === "done") {
            tip.textContent = "人工客服已接入，正在为您服务。";
            this.stopQueuePolling();
            return;
          }
        }
        this.queueTimer = window.setTimeout(poll, 5000);
      } catch {
        this.queueTimer = window.setTimeout(poll, 8000);
      }
    };
    void poll();
  }

  private stopQueuePolling() {
    if (this.queueTimer !== null) {
      window.clearTimeout(this.queueTimer);
      this.queueTimer = null;
    }
  }
}

customElements.define("xd-chat-widget", ChatWidget);
