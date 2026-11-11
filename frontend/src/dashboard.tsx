/** 运营看板（TSX 重构）：核心指标 + 比率条 + 会话漏斗 + 运行控制 + CSAT + Bad Case 管理（自动刷新）。 */
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  fetchBadCases,
  fetchCsat,
  fetchRuntime,
  fetchStats,
  setBadCaseStatus,
  updateRuntime,
  type BadCaseItem,
  type OpsStats,
  type RuntimeState,
} from "./api";

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return (v * 100).toFixed(1) + "%";
}

const MODE_LABEL: Record<string, { zh: string; desc: string; cls: string }> = {
  auto: { zh: "正常服务", desc: "RAG + 自动回答 + 转人工决策全开", cls: "" },
  handover: { zh: "全局转人工", desc: "半切：所有对话直接登记人工，不调 LLM", cls: "warn" },
  off: { zh: "维护下线", desc: "全切：统一回复维护话术，不登记不入队", cls: "warn" },
};

const BAD_STATUS_ZH: Record<string, string> = { open: "待处理", resolved: "已处理", ignored: "已忽略" };

interface CsatData {
  csat_total: number;
  csat_avg: number | null;
  csat_dist: Record<string, number>;
}

function TopBar({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div className="top">
      <div className="logo">答</div>
      <div>
        <h1>小答 · 运营看板</h1>
        <div className="sub">自动化率 / 转人工率 / 点赞率（口径：转过人工即归人工）</div>
      </div>
      <div className="nav">
        <a href="/dashboard.html" className="active">
          运营看板
        </a>
        <a href="/agent.html">坐席工作台</a>
        <a href="/kb.html">知识库后台</a>
      </div>
      <div className="actions">
        <button id="refresh" className="ghost" onClick={onRefresh}>
          刷新
        </button>
      </div>
    </div>
  );
}

function StatsCards({ stats }: { stats: OpsStats }) {
  const items: Array<[string, string, string, boolean?]> = [
    ["总咨询量", String(stats.total_sessions), "所有发起的新会话"],
    ["纯 Agent 解决", String(stats.agent_resolved), "全程未触发转人工"],
    ["转人工量", String(stats.handover), "会话中曾触发转人工", true],
    ["自动化率", pct(stats.auto_rate), "Agent 闭环占比"],
    ["转人工率", pct(stats.handover_rate), "= 1 − 自动化率"],
    [
      "点赞率",
      pct(stats.up_rate),
      stats.feedback_total ? `👍 ${stats.feedback_up} / 👎 ${stats.feedback_down}` : "暂无反馈",
    ],
    [
      "CSAT 平均分",
      stats.csat_avg != null ? `⭐ ${stats.csat_avg}` : "–",
      stats.csat_total ? `${stats.csat_total} 人打分` : "暂无打分",
    ],
  ];
  return (
    <div className="cards">
      {items.map(([label, num, sub, warn]) => (
        <div className="card" key={label}>
          <div className={warn ? "num warn" : "num"}>{num}</div>
          <div className="label">
            {label} · {sub}
          </div>
        </div>
      ))}
    </div>
  );
}

function RateBars({ stats }: { stats: OpsStats }) {
  const rows: Array<[string, number, string]> = [
    ["自动化率", stats.auto_rate, "#0066CC"],
    ["转人工率", stats.handover_rate, "#F59E0B"],
    ["点赞率", stats.up_rate ?? 0, "#22C55E"],
  ];
  return (
    <div>
      {rows.map(([name, val, color]) => {
        const width = Math.min(Math.max(val * 100, 0), 100);
        return (
          <div className="bar-row" key={name}>
            <div className="name">{name}</div>
            <div className="bar">
              <i style={{ width: `${width}%`, background: color }} />
            </div>
            <div className="val">{pct(val)}</div>
          </div>
        );
      })}
    </div>
  );
}

function Funnel({ stats }: { stats: OpsStats }) {
  const total = stats.total_sessions || 1;
  const a = stats.agent_resolved;
  const bc = stats.handover;
  const max = Math.max(a, bc, 1);
  const cols: Array<[string, number, string, string]> = [
    ["State A · 纯 Agent 闭环", a, "auto", String(a)],
    ["State B+C · 转人工", bc, "orange", String(bc)],
    ["总咨询量", total, "blue", String(total)],
  ];
  return (
    <div className="funnel">
      {cols.map(([label, val, cls, num]) => {
        const height = Math.max((val / max) * 100, val > 0 ? 6 : 0);
        return (
          <div className="col" key={label}>
            <div className="bar">
              <i className={cls} style={{ height: `${height}%` }} />
            </div>
            <div className="num">{num}</div>
            <div className="label">{label}</div>
          </div>
        );
      })}
    </div>
  );
}

function RuntimePanel({
  runtime,
  error,
  onMode,
  onGray,
  grayDraft,
}: {
  runtime: RuntimeState | null;
  error: string;
  onMode: (mode: RuntimeState["mode"]) => void;
  onGray: (percent: number) => void;
  grayDraft: number | null;
}) {
  const gray = grayDraft ?? runtime?.gray_percent ?? 0;
  let statusText = "";
  let statusCls = "rc-status";
  if (error) {
    statusText = error;
    statusCls = "rc-status warn";
  } else if (runtime) {
    const info = MODE_LABEL[runtime.mode];
    statusCls = `rc-status ${info.cls}`;
    const grayNote =
      runtime.gray_percent > 0 && runtime.gray_percent < 100
        ? ` · 灰度放量 ${runtime.gray_percent}%（按会话哈希分流，命中组 gray=true）`
        : runtime.gray_percent >= 100
          ? " · 灰度 100%（全量放行）"
          : "";
    statusText = `当前模式：${info.zh}（${info.desc}）${grayNote}`;
  }

  const modes: Array<{ mode: RuntimeState["mode"]; label: string; small: string; danger: boolean }> = [
    { mode: "auto", label: "正常服务", small: "RAG + 自动回答全开", danger: false },
    { mode: "handover", label: "全局转人工", small: "半切：所有对话直接登记人工", danger: true },
    { mode: "off", label: "维护下线", small: "全切：回复维护话术", danger: true },
  ];

  return (
    <div className="panel">
      <h2>⚡ 运行控制（Kill Switch + 灰度）</h2>
      <div className="rc-grid">
        <div>
          <div className="rc-actions">
            {modes.map((m) => {
              const active = runtime?.mode === m.mode;
              const cls = ["rc-btn", m.danger ? "danger" : "", active ? "active" : ""].filter(Boolean).join(" ");
              return (
                <button key={m.mode} className={cls} onClick={() => onMode(m.mode)}>
                  {m.label}
                  <small>{m.small}</small>
                </button>
              );
            })}
          </div>
          <div className="rc-slider">
            <span style={{ fontSize: 12, color: "#6B7280", flexShrink: 0 }}>灰度放量</span>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={gray}
              onChange={(e) => onGray(Number(e.target.value))}
            />
            <span className="val">{gray}%</span>
          </div>
        </div>
        <div className={statusCls}>{statusText}</div>
      </div>
      <div className="tip">
        Kill Switch 生效后即影响全部在线会话：全局转人工 = 所有新消息直接登记人工排队（不调 LLM）；维护下线 =
        统一回复维护话术（不登记不入队）。灰度 = 按会话稳定哈希放量（同会话全程同组），命中组在 init 响应中标记
        gray=true 便于观测。
      </div>
    </div>
  );
}

function CsatPanel({ data, error }: { data: CsatData | null; error: string }) {
  if (error) return <div className="error">{error}</div>;
  if (!data) return null;
  if (!data.csat_total) {
    return <div className="tip">暂无满意度数据 —— Widget 在转人工后弹出 1-5 星打分。</div>;
  }
  const max = Math.max(1, ...Object.values(data.csat_dist));
  return (
    <>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 34, fontWeight: 700, color: "#0066CC" }}>{data.csat_avg}</span>
        <span className="star">★★★★★</span>
        <span style={{ fontSize: 12, color: "#6B7280" }}>平均分 · 共 {data.csat_total} 人打分</span>
      </div>
      <div className="csat-bars">
        {[5, 4, 3, 2, 1].map((r) => {
          const cnt = data.csat_dist[String(r)] ?? 0;
          return (
            <div className="crow" key={r}>
              <div className="cname">{r} 星</div>
              <div className="cbar">
                <i style={{ width: `${(cnt / max) * 100}%` }} />
              </div>
              <div className="cnum">{cnt}</div>
            </div>
          );
        })}
      </div>
    </>
  );
}

function BadCasesTable({
  cases,
  error,
  onStatus,
}: {
  cases: BadCaseItem[];
  error: string;
  onStatus: (fid: number, status: "resolved" | "ignored") => void;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th style={{ width: "38%" }}>用户问题</th>
          <th>当时 Bot 回答</th>
          <th style={{ width: 120 }}>时间</th>
          <th style={{ width: 190 }}>状态 / 处理</th>
        </tr>
      </thead>
      <tbody>
        {error ? (
          <tr>
            <td colSpan={4} className="error">
              {error}
            </td>
          </tr>
        ) : cases.length === 0 ? (
          <tr>
            <td colSpan={4} className="empty">
              暂无点踩记录，说明当前回答质量不错 🎉
            </td>
          </tr>
        ) : (
          cases.map((c) => {
            const st = c.status ?? "open";
            return (
              <tr key={c.id}>
                <td className="q">{c.query}</td>
                <td className="a">{(c.answer ?? "").slice(0, 120)}</td>
                <td>{c.created_at}</td>
                <td>
                  <span className={`badge ${st}`}>{BAD_STATUS_ZH[st] ?? st}</span>
                  {c.note && (
                    <div className="tip" style={{ marginTop: 4 }}>
                      📝 {c.note}
                    </div>
                  )}
                  <div style={{ marginTop: 6 }}>
                    {st === "open" && (
                      <>
                        <button className="mini-btn" onClick={() => onStatus(c.id, "resolved")}>
                          标记已处理
                        </button>
                        <button className="mini-btn" onClick={() => onStatus(c.id, "ignored")}>
                          忽略
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            );
          })
        )}
      </tbody>
    </table>
  );
}

export function DashboardApp() {
  const [stats, setStats] = useState<OpsStats | null>(null);
  const [runtime, setRuntime] = useState<RuntimeState | null>(null);
  const [runtimeError, setRuntimeError] = useState("");
  const [grayDraft, setGrayDraft] = useState<number | null>(null);
  const [csat, setCsat] = useState<CsatData | null>(null);
  const [csatError, setCsatError] = useState("");
  const [badCases, setBadCases] = useState<BadCaseItem[]>([]);
  const [badCasesError, setBadCasesError] = useState("");
  const [error, setError] = useState("");

  const grayTimer = useRef<number | null>(null);

  const loadStats = async () => {
    try {
      setStats(await fetchStats());
      setError("");
    } catch (err) {
      setError(String(err));
    }
  };

  const loadRuntime = async () => {
    try {
      setRuntime(await fetchRuntime());
      setRuntimeError("");
    } catch (err) {
      setRuntimeError(`运行控制读取失败：${String(err)}`);
    }
  };

  const loadCsat = async () => {
    try {
      const s = await fetchCsat();
      setCsat({ csat_total: s.csat_total, csat_avg: s.csat_avg, csat_dist: s.csat_dist });
      setCsatError("");
    } catch (err) {
      setCsatError(String(err));
    }
  };

  const loadBadCases = async () => {
    try {
      setBadCases(await fetchBadCases(15));
      setBadCasesError("");
    } catch (err) {
      setBadCasesError(String(err));
    }
  };

  const loadAll = () => {
    void loadStats();
    void loadRuntime();
    void loadCsat();
    void loadBadCases();
  };

  useEffect(() => {
    loadAll();
    const timer = window.setInterval(loadAll, 15000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changeMode = (mode: RuntimeState["mode"]) => {
    updateRuntime({ mode })
      .then((st) => {
        setRuntime(st);
        setRuntimeError("");
      })
      .catch((err) => setRuntimeError(`切换失败：${String(err)}`));
  };

  const changeGray = (percent: number) => {
    setGrayDraft(percent);
    if (grayTimer.current !== null) window.clearTimeout(grayTimer.current);
    grayTimer.current = window.setTimeout(() => {
      updateRuntime({ gray_percent: percent })
        .then((st) => {
          setRuntime(st);
          setGrayDraft(null);
          setRuntimeError("");
        })
        .catch((err) => {
          setGrayDraft(null);
          setRuntimeError(`灰度设置失败：${String(err)}`);
        });
    }, 400);
  };

  const changeBadCaseStatus = async (fid: number, status: "resolved" | "ignored") => {
    let note = "";
    if (status === "resolved") {
      note = window.prompt("处理备注（可选，建议填写：改了什么知识库/怎么修的）：", "") ?? "";
    }
    try {
      await setBadCaseStatus(fid, status, note);
      await loadBadCases();
    } catch (err) {
      window.alert(`标记失败：${String(err)}`);
    }
  };

  return (
    <>
      <TopBar onRefresh={loadAll} />
      <div className="wrap">
        {stats && <StatsCards stats={stats} />}
        <RuntimePanel runtime={runtime} error={runtimeError} onMode={changeMode} onGray={changeGray} grayDraft={grayDraft} />
        <div className="panel">
          <h2>核心比率</h2>
          {stats && <RateBars stats={stats} />}
          <div className="tip">
            统计口径（plan 6.1 铁律）：会话中只要发生过转人工，整个会话归入转人工类，不计入自动化率；自动化率 +
            转人工率 = 100%。
          </div>
        </div>
        <div className="panel">
          <h2>会话漏斗（State A / B+C）</h2>
          {stats && <Funnel stats={stats} />}
          <div className="tip">
            State A 纯 Agent 闭环 · State B+C 发生过转人工（Agent 未闭环）。用于定位优化方向，不用于结果统计。
          </div>
        </div>
        <div className="panel">
          <h2>CSAT 满意度</h2>
          <CsatPanel data={csat} error={csatError} />
        </div>
        <div className="panel">
          <h2>最近 Bad Case（点踩）</h2>
          <BadCasesTable cases={badCases} error={badCasesError} onStatus={changeBadCaseStatus} />
        </div>
        <div className="error">{error}</div>
      </div>
    </>
  );
}

createRoot(document.getElementById("app") as HTMLElement).render(<DashboardApp />);
