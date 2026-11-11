/** 坐席工作台 V2.0（TSX 重构）：WebSocket 实时待办 + AI Copilot（工单卡片 / 快捷回复模板 / 内部系统查询）。 */
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  completeHandover,
  copilotQuery,
  fetchCopilot,
  fetchHandovers,
  generateTemplates,
  type CopilotTicket,
  type HandoverItem,
} from "./api";

// ---------------- AI Copilot ----------------

function TicketRow({ label, value }: { label: string; value?: string }) {
  return (
    <>
      <div className="k">{label}</div>
      <div className="v">{value || "—"}</div>
    </>
  );
}

function CopilotPanel({ item }: { item: HandoverItem }) {
  const [ticket, setTicket] = useState<CopilotTicket | null>(null);
  const [loadError, setLoadError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generatedOnce, setGeneratedOnce] = useState(false);
  const [templates, setTemplates] = useState<string[]>([]);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [querying, setQuerying] = useState<"logistics" | "order" | "refund" | null>(null);
  const [queryResult, setQueryResult] = useState<{ action: string; result: string } | null>(null);
  const [queryError, setQueryError] = useState("");

  useEffect(() => {
    let alive = true;
    fetchCopilot(item.id)
      .then((res) => {
        if (alive) setTicket(res.copilot?.ticket ?? {});
      })
      .catch((err) => {
        if (alive) setLoadError("工单卡片加载失败：" + String(err));
      });
    return () => {
      alive = false;
    };
  }, [item.id]);

  const runQuery = (action: "logistics" | "order" | "refund") => {
    setQuerying(action);
    setQueryError("");
    copilotQuery(item.id, action)
      .then((res) => setQueryResult({ action: res.action, result: res.result }))
      .catch((err) => {
        setQueryResult(null);
        setQueryError("查询失败：" + String(err));
      })
      .finally(() => setQuerying(null));
  };

  const genTemplates = () => {
    setGenerating(true);
    setTemplates([]);
    generateTemplates(item.id)
      .then((res) => setTemplates(res.templates))
      .catch((err) => {
        setQueryResult(null);
        setQueryError("模板生成失败：" + String(err));
      })
      .finally(() => {
        setGenerating(false);
        setGeneratedOnce(true);
      });
  };

  const copy = (tpl: string, index: number) => {
    void navigator.clipboard.writeText(tpl).then(() => {
      setCopiedIndex(index);
      window.setTimeout(() => setCopiedIndex(null), 1500);
    });
  };

  return (
    <div className="copilot">
      <div className="copilot-title">🤖 AI Copilot</div>
      {loadError ? (
        <div className="copilot-loading">{loadError}</div>
      ) : ticket === null ? (
        <div className="copilot-loading">生成工单卡片中…</div>
      ) : (
        <>
          <div className="ticket">
            <TicketRow label="核心诉求" value={ticket.user_intent} />
            <TicketRow label="订单号/关键信息" value={ticket.order_info} />
            <TicketRow label="Bot 已解答" value={ticket.bot_answered} />
            <TicketRow label="未解决问题" value={ticket.issue} />
          </div>
          <div className="copilot-btns">
            <button className="primary" disabled={generating} onClick={genTemplates}>
              {generating ? "生成中…" : generatedOnce ? "✨ 重新生成回复模板" : "✨ 生成回复模板"}
            </button>
            <button disabled={querying !== null} onClick={() => runQuery("logistics")}>
              查物流
            </button>
            <button disabled={querying !== null} onClick={() => runQuery("order")}>
              查订单
            </button>
            <button disabled={querying !== null} onClick={() => runQuery("refund")}>
              查退款
            </button>
          </div>
          {templates.length > 0 && (
            <div className="templates">
              {templates.map((tpl, i) => (
                <div className="template" key={`${i}-${tpl}`}>
                  {`${i + 1}. ${tpl}`}
                  <button onClick={() => copy(tpl, i)}>{copiedIndex === i ? "已复制 ✓" : "复制"}</button>
                </div>
              ))}
            </div>
          )}
          {queryResult && (
            <div className="query-result">
              <span className="mock-tag">开发期演示</span>
              <b>{queryResult.action}</b>：{queryResult.result}
            </div>
          )}
          {queryError && <div className="query-result">{queryError}</div>}
        </>
      )}
    </div>
  );
}

// ---------------- 卡片 ----------------

function HandoverCard({
  item,
  done,
  onChanged,
  onError,
}: {
  item: HandoverItem;
  done: boolean;
  onChanged: () => Promise<void>;
  onError: (text: string) => void;
}) {
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [completing, setCompleting] = useState(false);

  const complete = async () => {
    setCompleting(true);
    try {
      await completeHandover(item.id);
      await onChanged();
    } catch (err) {
      setCompleting(false);
      onError(String(err));
    }
  };

  return (
    <div className={done ? "card done-card" : "card"}>
      <div className="badge">{done ? "✓" : "#" + String(item.id)}</div>
      <div className="body">
        <div className="summary">{item.summary || "（无摘要）"}</div>
        <div className="meta">
          <span>
            联系方式：<b>{item.contact || "未留"}</b>
          </span>
          <span>
            时间：<b>{item.created_at}</b>
          </span>
          <span>
            会话：<b>{item.session_id.slice(0, 12)}…</b>
          </span>
        </div>
      </div>
      {!done && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end", flexShrink: 0 }}>
          <button
            className="done"
            style={{ background: "#7C3AED" }}
            disabled={copilotOpen}
            onClick={() => setCopilotOpen(true)}
          >
            🤖 AI Copilot
          </button>
          <button className="done" disabled={completing} onClick={() => void complete()}>
            处理完成
          </button>
        </div>
      )}
      {!done && copilotOpen && <CopilotPanel item={item} />}
    </div>
  );
}

// ---------------- 工作台主页面 ----------------

const WS_INTERVAL = 15000;

export function AgentApp() {
  const [waiting, setWaiting] = useState<HandoverItem[]>([]);
  const [done, setDone] = useState<HandoverItem[]>([]);
  const [wsOn, setWsOn] = useState(false);
  const [wsText, setWsText] = useState("连接中…");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const [waitingList, doneList] = await Promise.all([fetchHandovers("waiting"), fetchHandovers("done")]);
      setWaiting(waitingList);
      setDone(doneList);
      setError("");
    } catch (err) {
      setError(String(err));
    }
  };

  useEffect(() => {
    let ws: WebSocket | null = null;
    let wsDegraded = false;

    const degrade = () => {
      wsDegraded = true;
      if (ws) {
        ws.onclose = null;
        ws.close();
        ws = null;
      }
      setWsOn(false);
      setWsText("已降级为 15s 轮询");
    };

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss://" : "ws://";
      const url = `${proto}${location.host}/ws/agent`;
      let sock: WebSocket;
      try {
        sock = new WebSocket(url);
      } catch {
        degrade();
        return;
      }
      ws = sock;
      sock.onopen = () => {
        wsDegraded = false;
        setWsOn(true);
        setWsText("● 实时连接");
      };
      sock.onmessage = (msg) => {
        let data: { type?: string };
        try {
          data = JSON.parse(String(msg.data)) as { type?: string };
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
    };

    connect();
    void load();
    // 降级保底：WS 断开时仍保持待办最新
    const timer = window.setInterval(() => void load(), WS_INTERVAL);
    return () => {
      window.clearInterval(timer);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <div className="top">
        <div className="logo">答</div>
        <div>
          <h1>小答 · 坐席工作台</h1>
          <div className="sub">转人工待办 / AI Copilot（工单卡片 + 快捷回复 + 内部系统查询）</div>
        </div>
        <div className="nav">
          <a href="/dashboard.html">运营看板</a>
          <a href="/agent.html" className="active">
            坐席工作台
          </a>
          <a href="/kb.html">知识库后台</a>
        </div>
        <div className={wsOn ? "ws-state on" : "ws-state off"}>{wsText}</div>
        <div className="actions">
          <button id="refresh" className="ghost" onClick={() => void load()}>
            刷新
          </button>
        </div>
      </div>
      <div className="wrap">
        <div className="stats">
          <div className="stat">
            <div className="num">{waiting.length}</div>
            <div className="label">等待处理</div>
          </div>
          <div className="stat">
            <div className="num">{done.length}</div>
            <div className="label">已完成</div>
          </div>
          <div className="stat">
            <div className="num">{waiting.length + done.length}</div>
            <div className="label">累计转入</div>
          </div>
        </div>
        <div className="sec-title">
          待办列表 <span className="cnt">{waiting.length}</span>
        </div>
        <div>
          {waiting.length === 0 ? (
            <div className="empty">🎉 暂无待办，所有转人工都已处理</div>
          ) : (
            waiting.map((it) => (
              <HandoverCard key={it.id} item={it} done={false} onChanged={load} onError={setError} />
            ))
          )}
        </div>
        <div className="sec-title">
          已完成 <span className="cnt">{done.length}</span>
        </div>
        <div className="done-list">
          {done.slice(0, 20).map((it) => (
            <HandoverCard key={it.id} item={it} done onChanged={load} onError={setError} />
          ))}
        </div>
        <div className="error">{error}</div>
      </div>
    </>
  );
}

createRoot(document.getElementById("app") as HTMLElement).render(<AgentApp />);
