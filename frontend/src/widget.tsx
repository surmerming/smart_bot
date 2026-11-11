/** 聊天 Widget Web Component（TSX 重构）：<xd-chat-widget>。
 *
 * 两种形态（attribute `mode`）：
 *   - inline  内嵌面板（官网 Hero 演示区使用）
 *   - floating 右下角悬浮按钮 + 弹出面板（嵌入任意官网）
 *
 * 附加属性：
 *   - api-base  后端地址（缺省同源，走 /api 代理）
 *   - brand     品牌名（缺省取后端 init 返回）
 *
 * Shadow DOM 内挂载 React 根节点，样式与宿主页面完全隔离。
 */
import { useEffect, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  chatInit,
  fetchQueueStatus,
  manualHandover,
  sendFeedback,
  sendOtp,
  submitCsat,
  verifyOtp,
  type QuickChip,
} from "./api";
import { postSSE } from "./sse-client";
import widgetCss from "./widget.css?inline";

const STORE_KEY = "xd_anonymous_session_id";
// OTP 触发词：涉及账户安全 / 验证码的敏感引导
const OTP_TRIGGER_RE = /忘记密码|找回密码|改手机号|修改手机号|换绑|验证码|收不到短信/;
const DEFAULT_QUEUE_TEXT = "已转人工排队（留言模式）：客服上线后第一时间回复，排队期间可继续咨询其他问题。";
const JOINED_TEXT = "人工客服已接入，正在为您服务。";

let msgSeq = 0;
const nextMsgId = (): number => (msgSeq += 1);

interface ChatMsg {
  id: number;
  role: "user" | "assistant";
  content: string;
  query?: string;
  messageId?: string;
  faqIds?: string[];
  handover?: boolean;
  queueText?: string;
  showCsat?: boolean;
  showOtp?: boolean;
}

type WidgetMode = "floating" | "inline";

interface WidgetProps {
  mode: WidgetMode;
  apiBase: string;
  brand: string;
  onSession: (sessionId: string, visitorToken: string) => void;
  onReady: (notice: (text: string) => void) => void;
}

function Typing() {
  return (
    <span className="xd-typing">
      <span />
      <span />
      <span />
    </span>
  );
}

function CsatCard({
  sessionId,
  visitorToken,
}: {
  sessionId: string;
  visitorToken: string;
}) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState<number | null>(null);

  if (done !== null) {
    return <div className="xd-csat-done">已记录您的 {done} 星评分，感谢反馈！</div>;
  }

  const submit = async () => {
    setSubmitting(true);
    try {
      await submitCsat({ session_id: sessionId, visitor_token: visitorToken, rating, comment: comment.trim() || undefined });
      setDone(rating);
    } catch (err) {
      setSubmitting(false);
      window.alert(`评分提交失败：${String(err)}`);
    }
  };

  return (
    <div className="xd-csat">
      <div className="xd-csat-q">本次服务体验如何？请为小答打分（1-5 星）</div>
      <div className="xd-csat-stars">
        {[5, 4, 3, 2, 1].map((v) => (
          <span key={v} className={v <= rating ? "on" : ""} onClick={() => setRating(v)}>
            ★
          </span>
        ))}
      </div>
      <textarea placeholder="补充意见（可选）" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
      <button className="xd-csat-submit" disabled={rating === 0 || submitting} onClick={() => void submit()}>
        提交评分
      </button>
    </div>
  );
}

function OtpCard({
  sessionId,
  visitorToken,
}: {
  sessionId: string;
  visitorToken: string;
}) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [demoText, setDemoText] = useState("");
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [done, setDone] = useState(false);

  if (done) {
    return <div className="xd-otp-done">手机号验证通过，可继续安全操作（有效期内会话已标记）</div>;
  }

  const sendCode = async () => {
    const value = phone.trim();
    if (!/^1\d{10}$/.test(value)) {
      window.alert("请输入 11 位手机号");
      return;
    }
    setSending(true);
    try {
      const res = await sendOtp({ session_id: sessionId, visitor_token: visitorToken, phone: value });
      // 演示模式：后端直接返回验证码；生产接入短信服务后此段不展示
      setDemoText(
        res.mock && res.code
          ? `演示模式验证码：${res.code}（${res.ttl_minutes} 分钟内有效）`
          : `验证码已发送至 ${value}（${res.ttl_minutes} 分钟内有效）`,
      );
      setSent(true);
    } catch (err) {
      window.alert(`发送失败：${String(err)}`);
    } finally {
      setSending(false);
    }
  };

  const verify = async () => {
    setVerifying(true);
    try {
      await verifyOtp({ session_id: sessionId, visitor_token: visitorToken, phone: phone.trim(), code: code.trim() });
      setDone(true);
    } catch (err) {
      setVerifying(false);
      window.alert(`验证失败：${String(err)}`);
    }
  };

  return (
    <div className="xd-otp">
      <div className="xd-otp-q">涉及账户安全操作，需要先验证手机号（演示环境，验证码直接展示）</div>
      <div className="xd-otp-row">
        <input placeholder="请输入手机号" inputMode="numeric" value={phone} onChange={(e) => setPhone(e.target.value)} />
      </div>
      {sent && (
        <div className="xd-otp-row">
          <input placeholder="6 位验证码" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
          <button className="xd-otp-verify" disabled={verifying} onClick={() => void verify()}>
            验证
          </button>
        </div>
      )}
      <button className="xd-otp-send" disabled={sending} onClick={() => void sendCode()}>
        {sent ? "重新发送" : "发送验证码"}
      </button>
      {demoText && <div className="xd-otp-demo">{demoText}</div>}
    </div>
  );
}

function MessageRow({
  msg,
  typing,
  sessionId,
  visitorToken,
  showCsat,
  showOtp,
  onFeedback,
}: {
  msg: ChatMsg;
  typing: boolean;
  sessionId: string;
  visitorToken: string;
  showCsat: boolean;
  showOtp: boolean;
  onFeedback: (msg: ChatMsg, value: "up" | "down") => void;
}) {
  const faqBadge = msg.faqIds?.length
    ? msg.faqIds.length === 1 && msg.faqIds[0].includes("·")
      ? `命中 ${msg.faqIds[0]}`
      : `命中 ${msg.faqIds.join(" · ")} · 知识库`
    : null;

  return (
    <div className={msg.role === "user" ? "xd-msg user" : "xd-msg bot"}>
      <div className="xd-bubble">
        {typing ? (
          msg.content ? (
            <>
              {msg.content}
              <span className="xd-caret" />
            </>
          ) : (
            <Typing />
          )
        ) : (
          msg.content
        )}
      </div>
      {msg.role === "assistant" && (
        <>
          {faqBadge && <div className="xd-faq-badge">{faqBadge}</div>}
          {msg.handover && <div className="xd-handover-tip">{msg.queueText ?? DEFAULT_QUEUE_TEXT}</div>}
          {showCsat && <CsatCard sessionId={sessionId} visitorToken={visitorToken} />}
          <div className="xd-feedback">
            <span>这个回答有帮助吗？</span>
            <button data-v="up" title="没问题" onClick={() => onFeedback(msg, "up")}>
              👍
            </button>
            <button data-v="down" title="没解决" onClick={() => onFeedback(msg, "down")}>
              👎
            </button>
          </div>
          {showOtp && <OtpCard sessionId={sessionId} visitorToken={visitorToken} />}
        </>
      )}
    </div>
  );
}

function ChatWidgetApp({ mode, apiBase, brand: brandProp, onSession, onReady }: WidgetProps) {
  const [open, setOpen] = useState(mode === "inline");
  const [brand, setBrand] = useState(brandProp);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [chips, setChips] = useState<QuickChip[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamingId, setStreamingId] = useState<number | null>(null);
  const [unread, setUnread] = useState(0);
  const [errorText, setErrorText] = useState("");

  const initializedRef = useRef(false);
  const openRef = useRef(open);
  const streamingRef = useRef(false);
  const sessionRef = useRef("");
  const visitorTokenRef = useRef("");
  const csatShownRef = useRef(false);
  const otpShownRef = useRef(false);

  const messagesRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const queueMsgIdRef = useRef<number | null>(null);
  const queueWsRef = useRef<WebSocket | null>(null);
  const queueTimerRef = useRef<number | null>(null);

  useEffect(() => {
    setBrand(brandProp);
  }, [brandProp]);

  useEffect(() => {
    openRef.current = open;
  }, [open]);

  useEffect(() => {
    const el = messagesRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, errorText]);

  // ---------------- 排队进度：WebSocket 实时（失败自动降级轮询） ----------------
  const setQueueText = (text: string) => {
    const mid = queueMsgIdRef.current;
    if (mid === null) return;
    setMessages((prev) => prev.map((m) => (m.id === mid ? { ...m, queueText: text } : m)));
  };

  const stopQueueLive = () => {
    if (queueWsRef.current !== null) {
      const ws = queueWsRef.current;
      queueWsRef.current = null;
      ws.onclose = null;
      ws.close();
    }
  };

  const stopQueuePolling = () => {
    if (queueTimerRef.current !== null) {
      window.clearTimeout(queueTimerRef.current);
      queueTimerRef.current = null;
    }
  };

  const startQueuePolling = (queueId: number) => {
    stopQueuePolling();
    stopQueueLive();
    const poll = async () => {
      try {
        const st = await fetchQueueStatus(queueId);
        if (st.status === "waiting") {
          setQueueText(
            st.position
              ? `已转人工排队：前面还有 ${st.ahead ?? 0} 人，客服上线后第一时间回复，排队期间可继续咨询其他问题。`
              : DEFAULT_QUEUE_TEXT,
          );
        } else if (st.status === "done") {
          setQueueText(JOINED_TEXT);
          stopQueuePolling();
          return;
        }
        queueTimerRef.current = window.setTimeout(poll, 5000);
      } catch {
        queueTimerRef.current = window.setTimeout(poll, 8000);
      }
    };
    void poll();
  };

  const wsUrl = (path: string): string => {
    if (apiBase) return `${apiBase.replace(/^http/, "ws")}${path}`;
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    return `${proto}${location.host}${path}`;
  };

  const fallbackPolling = (queueId: number) => {
    // stopQueueLive 主动关闭会先把 onclose 置空，不会走到这里；走到这里说明连接确实断了 → 降级轮询
    if (queueWsRef.current === null) return;
    queueWsRef.current = null;
    startQueuePolling(queueId);
  };

  const startQueueLive = (queueId: number) => {
    stopQueueLive();
    stopQueuePolling();
    let ws: WebSocket;
    try {
      ws = new WebSocket(
        wsUrl(
          `/ws/user?session_id=${encodeURIComponent(sessionRef.current)}&visitor_token=${encodeURIComponent(
            visitorTokenRef.current,
          )}`,
        ),
      );
    } catch {
      startQueuePolling(queueId);
      return;
    }
    queueWsRef.current = ws;
    ws.onmessage = (msg) => {
      let data: { type?: string; queue_id?: number; position?: number | null; ahead?: number | null; status?: string };
      try {
        data = JSON.parse(String(msg.data)) as typeof data;
      } catch {
        return;
      }
      if (data.type === "queue") {
        if (data.status === "waiting") {
          setQueueText(
            data.position && data.position > 0
              ? `已转人工排队：前面还有 ${data.ahead ?? 0} 人，客服上线后第一时间回复，排队期间可继续咨询其他问题。`
              : DEFAULT_QUEUE_TEXT,
          );
        } else if (data.status === "done") {
          setQueueText(JOINED_TEXT);
          stopQueueLive();
        }
      } else if (data.type === "agent_joined") {
        setQueueText(JOINED_TEXT);
        stopQueueLive();
      }
    };
    ws.onerror = () => fallbackPolling(queueId);
    ws.onclose = () => fallbackPolling(queueId);
  };

  useEffect(() => {
    const notice = (text: string) => setErrorText(text);
    onReady(notice);
    return () => {
      stopQueuePolling();
      stopQueueLive();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------- 初始化 ----------------
  const init = async () => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    try {
      const stored = localStorage.getItem(STORE_KEY) || undefined;
      const res = await chatInit({ session_id: stored });
      localStorage.setItem(STORE_KEY, res.session_id);
      sessionRef.current = res.session_id;
      visitorTokenRef.current = res.visitor_token;
      onSession(res.session_id, res.visitor_token);
      const nextBrand = res.brand_name || brandProp;
      setBrand(nextBrand);
      setChips(res.quick_chips || []);

      const history: ChatMsg[] = (res.history || []).map((m) => ({
        id: nextMsgId(),
        role: m.role,
        content: m.content,
      }));
      if (!history.length) {
        history.push({ id: nextMsgId(), role: "assistant", content: `你好，我是${nextBrand}(AI客服)～有什么可以帮你的？` });
        // inline 演示区：补一条静态演示对话（1:1 对齐设计稿 s_hero.png）
        if (mode === "inline") {
          history.push({ id: nextMsgId(), role: "user", content: "拆了包装还能退吗？" });
          history.push({
            id: nextMsgId(),
            role: "assistant",
            content: "支持7天无理由退换～拆封试用不影响，只要包装配件齐全就行，放心冲！",
            faqIds: ["FAQ_001 · 退换货政策 · 相似度 0.91"],
          });
        }
      }
      setMessages(history);
    } catch (err) {
      setErrorText("连不上客服服务，请确认后端已启动");
      console.error("[xd-chat] init failed:", err);
    }
  };

  useEffect(() => {
    if (mode === "inline") void init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------------- 发送与流式 ----------------
  const send = async (text?: string) => {
    const content = (text ?? input).trim();
    if (!content || streamingRef.current) return;
    setInput("");
    setChips([]);

    const userMsg: ChatMsg = { id: nextMsgId(), role: "user", content };
    const botId = nextMsgId();
    const botMsg: ChatMsg = { id: botId, role: "assistant", content: "" };
    setMessages((prev) => [...prev, userMsg, botMsg]);

    streamingRef.current = true;
    setStreaming(true);
    setStreamingId(botId);
    let lastMeta: Record<string, unknown> = {};
    let contentAcc = "";
    let messageId = "";
    let handover = false;

    try {
      await postSSE(
        `${apiBase}/api/v1/chat/stream`,
        { session_id: sessionRef.current, visitor_token: visitorTokenRef.current, message: content },
        (ev) => {
          if (ev.event === "meta") lastMeta = ev.data;
          if (ev.event === "text") {
            contentAcc += String(ev.data.content ?? "");
            setMessages((prev) => prev.map((m) => (m.id === botId ? { ...m, content: contentAcc } : m)));
          }
          if (ev.event === "done") {
            messageId = String(ev.data.message_id ?? "");
            handover = Boolean(ev.data.handover);
          }
          // 转人工后拿 queue_id → 优先 WebSocket 实时排队，失败降级轮询
          if (ev.event === "summary") {
            const qid = ev.data.queue_id;
            if (typeof qid === "number" && qid > 0) startQueueLive(qid);
          }
        },
      );
    } catch (err) {
      const errText = String(err);
      contentAcc =
        errText.includes("429") || errText.includes("请求太频繁")
          ? "请求太频繁啦，请稍等片刻再试～"
          : "网络开小差了，请稍后再试～";
      console.error("[xd-chat] stream failed:", err);
    }

    const faqs = (lastMeta.faqs as { id: string; title: string; score: number }[] | undefined) || [];
    const metaFaqIds = (lastMeta.faq_ids as string[] | undefined) || [];
    let faqIds: string[] | undefined;
    if (faqs.length) {
      faqIds = [`${faqs[0].id} · ${faqs[0].title} · 相似度 ${faqs[0].score.toFixed(2)}`];
    } else if (metaFaqIds.length) {
      faqIds = metaFaqIds;
    }

    // CSAT：转人工后弹出满意度打分（每会话一次）
    let showCsat = false;
    if (handover && !csatShownRef.current) {
      csatShownRef.current = true;
      showCsat = true;
    }
    // OTP：涉及账户安全的敏感引导 → 弹出手机号验证卡片（每会话一次）
    let showOtp = false;
    if (!otpShownRef.current && OTP_TRIGGER_RE.test(content)) {
      otpShownRef.current = true;
      showOtp = true;
    }
    if (handover) queueMsgIdRef.current = botId;

    setMessages((prev) =>
      prev.map((m) =>
        m.id === botId
          ? {
              ...m,
              content: contentAcc,
              messageId,
              handover,
              faqIds,
              showCsat,
              showOtp,
              query: content,
              queueText: handover ? DEFAULT_QUEUE_TEXT : undefined,
            }
          : m,
      ),
    );

    // 快捷按钮：软转人工 / 排队期间继续咨询
    const quickReplies = (lastMeta.quick_replies as QuickChip[] | undefined) || [];
    if (quickReplies.length) setChips(quickReplies);

    // floating 模式：面板关闭时累计未读
    if (!openRef.current) setUnread((u) => u + 1);

    streamingRef.current = false;
    setStreaming(false);
    setStreamingId(null);
  };

  const togglePanel = (force?: boolean) => {
    const next = force ?? !open;
    setOpen(next);
    openRef.current = next;
    if (next) {
      setUnread(0);
      if (!initializedRef.current) void init();
      window.setTimeout(() => inputRef.current?.focus(), 50);
    }
  };

  // ---------------- 反馈 ----------------
  const submitFeedback = async (msg: ChatMsg, value: "up" | "down") => {
    try {
      await sendFeedback({
        session_id: sessionRef.current,
        message_id: msg.messageId || undefined,
        value,
        query: msg.query,
        answer: msg.content,
      });
    } catch (err) {
      console.error("[xd-chat] feedback failed:", err);
    }
  };

  return (
    <>
      {mode === "floating" && (
        <button className="xd-fab" title="打开小答客服" onClick={() => togglePanel()}>
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
          <span className="xd-badge" style={{ display: unread > 0 ? "flex" : "none" }}>
            {unread}
          </span>
        </button>
      )}
      <div
        className={mode === "inline" ? "xd-panel inline" : "xd-panel"}
        style={{ display: open ? "flex" : "none" }}
      >
        <div className="xd-header">
          <div className="xd-header-logo">答</div>
          <div>
            <div className="xd-header-title">{brand} · AI客服</div>
            <div className="xd-header-status">
              <span className="xd-dot" />
              在线 · 通常秒回
            </div>
          </div>
          <button className="xd-close" aria-label="关闭" onClick={() => togglePanel(false)}>
            ×
          </button>
        </div>
        <div className="xd-messages" ref={messagesRef}>
          {messages.map((msg) => (
            <MessageRow
              key={msg.id}
              msg={msg}
              typing={streamingId === msg.id}
              sessionId={sessionRef.current}
              visitorToken={visitorTokenRef.current}
              showCsat={Boolean(msg.showCsat)}
              showOtp={Boolean(msg.showOtp)}
              onFeedback={(m, value) => void submitFeedback(m, value)}
            />
          ))}
          {errorText && <div className="xd-error">{errorText}</div>}
        </div>
        {chips.length > 0 && (
          <div className="xd-chips">
            {chips.map((chip) => (
              <button key={chip.value} className="xd-chip" onClick={() => void send(chip.value)}>
                {chip.label}
              </button>
            ))}
          </div>
        )}
        <div className="xd-disclaimer">AI 客服提供的信息仅供参考，涉及交易 / 价格以结算页或人工客服最终确认为准</div>
        <form
          className="xd-input-bar"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <input
            ref={inputRef}
            placeholder="输入你的问题…"
            autoComplete="off"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button type="submit" disabled={streaming}>
            发送
          </button>
        </form>
      </div>
    </>
  );
}

export class ChatWidget extends HTMLElement {
  private mode: WidgetMode = "floating";
  private apiBase = "";
  private brand = "小答";
  private sessionId = "";
  private visitorToken = "";
  private notice: ((text: string) => void) | null = null;
  private root: Root | null = null;
  private container: HTMLElement | null = null;

  static get observedAttributes(): string[] {
    return ["mode", "api-base", "brand"];
  }

  attributeChangedCallback(name: string, _old: string | null, value: string | null) {
    if (name === "mode") this.mode = value === "inline" ? "inline" : "floating";
    if (name === "api-base") this.apiBase = (value ?? "").replace(/\/$/, "");
    if (name === "brand") this.brand = value || "小答";
    this.renderApp();
  }

  connectedCallback() {
    if (!this.container) {
      const shadow = this.shadowRoot ?? this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = widgetCss;
      this.container = document.createElement("div");
      shadow.append(style, this.container);
      this.root = createRoot(this.container);
    }
    this.renderApp();
  }

  private renderApp() {
    this.root?.render(
      <ChatWidgetApp
        mode={this.mode}
        apiBase={this.apiBase}
        brand={this.brand}
        onSession={(sessionId, visitorToken) => {
          this.sessionId = sessionId;
          this.visitorToken = visitorToken;
        }}
        onReady={(notice) => {
          this.notice = notice;
        }}
      />,
    );
  }

  public async requestHandover(contact?: string) {
    try {
      const res = await manualHandover({
        session_id: this.sessionId,
        visitor_token: this.visitorToken,
        contact,
      });
      if (res.ok) this.notice?.(res.message || "已登记转人工");
    } catch (err) {
      console.error("[xd-chat] handover failed:", err);
    }
  }
}

customElements.define("xd-chat-widget", ChatWidget);
