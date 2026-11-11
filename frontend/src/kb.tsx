/** 知识库后台 V2.0（TSX 重构）：FAQ CRUD + 草稿审批流 + 版本历史。角色：运营（编辑）/ 主管（审批）。 */
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  approveDraft,
  createFAQ,
  deleteDraft,
  deleteFAQ,
  fetchDrafts,
  fetchFAQs,
  fetchVersions,
  KB_ACTIONS,
  rebuildKB,
  rejectDraft,
  rollbackVersion,
  submitDraft,
  updateFAQ,
  type FAQItem,
  type FAQPayload,
  type KBDraft,
  type KBVersion,
} from "./api";

const ROLE_KEY = "xd_kb_role";
type Role = "ops" | "approver";
type Tab = "faqs" | "drafts" | "versions";

const CATEGORY_ZH: Record<string, string> = { aftersales: "售后", presales: "售前", transaction: "交易", account: "账号" };

function CatZh({ category }: { category: string }) {
  return <>{CATEGORY_ZH[category] ?? category}</>;
}

function RiskBadge({ level }: { level: string }) {
  const map: Record<string, { cls: string; zh: string }> = {
    low: { cls: "green", zh: "低" },
    mid: { cls: "orange", zh: "中" },
    high: { cls: "red", zh: "高" },
  };
  const item = map[level];
  return item ? <span className={`badge ${item.cls}`}>{item.zh}</span> : <>{level}</>;
}

function FaqDraftBadge({ status }: { status?: string }) {
  const map: Record<string, { cls: string; zh: string }> = {
    draft: { cls: "gray", zh: "有草稿" },
    pending: { cls: "orange", zh: "待审核" },
    rejected: { cls: "red", zh: "已驳回" },
  };
  const item = status ? map[status] : undefined;
  return item ? <span className={`badge ${item.cls}`}>{item.zh}</span> : null;
}

function DraftStatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; zh: string }> = {
    draft: { cls: "gray", zh: "草稿" },
    pending: { cls: "orange", zh: "待审" },
    rejected: { cls: "red", zh: "已驳回" },
    published: { cls: "green", zh: "已生效" },
  };
  const item = map[status];
  return item ? <span className={`badge ${item.cls}`}>{item.zh}</span> : <>{status}</>;
}

function VersionActionBadge({ action }: { action: string }) {
  const map: Record<string, { cls: string; zh: string }> = {
    create: { cls: "green", zh: "新建" },
    update: { cls: "blue", zh: "编辑" },
    delete: { cls: "red", zh: "删除" },
  };
  const item = map[action];
  return item ? <span className={`badge ${item.cls}`}>{item.zh}</span> : <>{action}</>;
}

interface FormState {
  question: string;
  category: FAQPayload["category"];
  risk: FAQPayload["risk_level"];
  variants: string;
  answer: string;
  followUp: string;
}

const EMPTY_FORM: FormState = {
  question: "",
  category: "aftersales",
  risk: "low",
  variants: "",
  answer: "",
  followUp: "",
};

function TopBar({
  role,
  onRole,
  onRebuild,
  onRefresh,
}: {
  role: Role;
  onRole: (role: Role) => void;
  onRebuild: () => void;
  onRefresh: () => void;
}) {
  return (
    <div className="top">
      <div className="logo">答</div>
      <div>
        <h1>小答 · 知识库后台</h1>
        <div className="sub">FAQ 编辑走「草稿 → 审核 → 生效」审批流，生效即热更新，无需重启</div>
      </div>
      <div className="nav">
        <a href="/dashboard.html">运营看板</a>
        <a href="/agent.html">坐席工作台</a>
        <a href="/kb.html" className="active">
          知识库后台
        </a>
      </div>
      <div className="actions">
        <div className="role">
          当前角色
          <select value={role} onChange={(e) => onRole(e.target.value as Role)}>
            <option value="ops">运营（编辑）</option>
            <option value="approver">主管（审批）</option>
          </select>
        </div>
        <button id="rebuild" className="ghost" onClick={onRebuild}>
          热更新
        </button>
        <button id="refresh" className="ghost" onClick={onRefresh}>
          刷新
        </button>
      </div>
    </div>
  );
}

function Cards({ faqTotal, drafts, versions }: { faqTotal: number; drafts: KBDraft[]; versions: KBVersion[] }) {
  const pendingCount = drafts.filter((d) => d.status === "pending").length;
  const draftCount = drafts.filter((d) => d.status === "draft" || d.status === "rejected").length;
  const items: Array<[string, string, string, boolean?]> = [
    ["FAQ 总数", String(faqTotal), "已生效知识库条目"],
    ["待审核", String(pendingCount), "等待主管审批", pendingCount > 0],
    ["草稿 / 已驳回", String(draftCount), "未生效的变更"],
    ["版本记录", String(versions.length), "审批生效的历史快照"],
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

function FaqTable({
  faqs,
  onEdit,
  onDelete,
}: {
  faqs: FAQItem[];
  onEdit: (faq: FAQItem) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th style={{ width: 90 }}>ID</th>
          <th style={{ width: "34%" }}>标准问法</th>
          <th>分类</th>
          <th>风险</th>
          <th>状态</th>
          <th style={{ width: 150 }}>操作</th>
        </tr>
      </thead>
      <tbody>
        {faqs.length === 0 ? (
          <tr>
            <td colSpan={6} className="empty">
              暂无 FAQ（可调整筛选条件或新建）
            </td>
          </tr>
        ) : (
          faqs.map((f) => (
            <tr key={f.id}>
              <td>{f.id}</td>
              <td>
                <div className="q">{f.standard_question}</div>
              </td>
              <td>
                <CatZh category={f.category} />
              </td>
              <td>
                <RiskBadge level={f.risk_level} />
              </td>
              <td>
                <FaqDraftBadge status={f.draft_status} />
              </td>
              <td>
                <button className="btn ghost small" onClick={() => onEdit(f)}>
                  编辑
                </button>{" "}
                <button className="btn danger small" onClick={() => onDelete(f.id)}>
                  删除
                </button>
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function DraftTable({
  drafts,
  role,
  onSubmit,
  onApprove,
  onReject,
  onDrop,
}: {
  drafts: KBDraft[];
  role: Role;
  onSubmit: (id: number) => void;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  onDrop: (id: number) => void;
}) {
  const isApprover = role === "approver";
  return (
    <table>
      <thead>
        <tr>
          <th style={{ width: 70 }}>草稿</th>
          <th style={{ width: 90 }}>FAQ</th>
          <th style={{ width: 70 }}>动作</th>
          <th style={{ width: "36%" }}>内容摘要</th>
          <th style={{ width: 80 }}>状态</th>
          <th style={{ width: 180 }}>操作</th>
        </tr>
      </thead>
      <tbody>
        {drafts.length === 0 ? (
          <tr>
            <td colSpan={6} className="empty">
              暂无草稿
            </td>
          </tr>
        ) : (
          drafts.map((d) => (
            <tr key={d.id}>
              <td>#{d.id}</td>
              <td>{d.faq_id}</td>
              <td>{KB_ACTIONS[d.action] ?? d.action}</td>
              <td>
                {d.action === "delete" ? (
                  <span className="badge red">删除 {d.faq_id}</span>
                ) : (
                  d.payload?.standard_question ?? ""
                )}
              </td>
              <td>
                <DraftStatusBadge status={d.status} />
              </td>
              <td>
                {d.status === "draft" || d.status === "rejected" ? (
                  <>
                    <button className="btn primary small" onClick={() => onSubmit(d.id)}>
                      提交审核
                    </button>{" "}
                    <button className="btn ghost small" onClick={() => onDrop(d.id)}>
                      撤销
                    </button>
                  </>
                ) : d.status === "pending" ? (
                  isApprover ? (
                    <>
                      <button className="btn success small" onClick={() => onApprove(d.id)}>
                        通过
                      </button>{" "}
                      <button className="btn danger small" onClick={() => onReject(d.id)}>
                        驳回
                      </button>
                    </>
                  ) : (
                    <span className="tip">待主管审批</span>
                  )
                ) : (
                  <span className="tip">已生效</span>
                )}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function VersionTable({
  versions,
  shown,
  onToggleSnapshot,
  onRollback,
}: {
  versions: KBVersion[];
  shown: Record<number, boolean>;
  onToggleSnapshot: (id: number) => void;
  onRollback: (id: number) => void;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th style={{ width: 150 }}>时间</th>
          <th style={{ width: 90 }}>FAQ</th>
          <th style={{ width: 70 }}>动作</th>
          <th style={{ width: 90 }}>操作人</th>
          <th>快照</th>
        </tr>
      </thead>
      <tbody>
        {versions.length === 0 ? (
          <tr>
            <td colSpan={5} className="empty">
              暂无版本记录（审批生效后产生）
            </td>
          </tr>
        ) : (
          versions.map((v) => {
            const snapshotText = v.snapshot ? JSON.stringify(v.snapshot, null, 2) : "（无快照）";
            return (
              <tr key={v.id}>
                <td>{v.created_at}</td>
                <td>{v.faq_id}</td>
                <td>
                  <VersionActionBadge action={v.action} />
                </td>
                <td>{v.operator}</td>
                <td>
                  <button className="btn ghost small" onClick={() => onToggleSnapshot(v.id)}>
                    查看快照
                  </button>{" "}
                  <button className="btn warn small" onClick={() => onRollback(v.id)}>
                    回滚到此版本
                  </button>
                  <div className={shown[v.id] ? "versions-snapshot show" : "versions-snapshot"}>{snapshotText}</div>
                </td>
              </tr>
            );
          })
        )}
      </tbody>
    </table>
  );
}

function FaqFormModal({
  editingId,
  form,
  onChange,
  onClose,
  onSave,
}: {
  editingId: string | null;
  form: FormState;
  onChange: (patch: Partial<FormState>) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div
      className="modal-mask show"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal">
        <h3>{editingId ? `编辑 FAQ · ${editingId}` : "新建 FAQ"}</h3>
        <div className="form-row">
          <label>标准问法（必填，≤200 字）</label>
          <input
            maxLength={200}
            placeholder="如：支持7天无理由退换吗？"
            value={form.question}
            onChange={(e) => onChange({ question: e.target.value })}
          />
        </div>
        <div className="form-row">
          <div className="row2">
            <div>
              <label>分类</label>
              <select value={form.category} onChange={(e) => onChange({ category: e.target.value as FAQPayload["category"] })}>
                <option value="aftersales">售后</option>
                <option value="presales">售前</option>
                <option value="transaction">交易</option>
                <option value="account">账号</option>
              </select>
            </div>
            <div>
              <label>风险等级</label>
              <select value={form.risk} onChange={(e) => onChange({ risk: e.target.value as FAQPayload["risk_level"] })}>
                <option value="low">低</option>
                <option value="mid">中</option>
                <option value="high">高</option>
              </select>
            </div>
          </div>
        </div>
        <div className="form-row">
          <label>变体问法（每行一条，用户口语化问法）</label>
          <textarea
            placeholder={"每行一条，如：\n可以退吗\n不满意能换吗"}
            value={form.variants}
            onChange={(e) => onChange({ variants: e.target.value })}
          />
        </div>
        <div className="form-row">
          <label>答案（必填）</label>
          <textarea
            style={{ minHeight: 110 }}
            placeholder="机器人将基于此内容回答用户"
            value={form.answer}
            onChange={(e) => onChange({ answer: e.target.value })}
          />
        </div>
        <div className="form-row">
          <label>追问建议（每行一条，可留空）</label>
          <textarea
            placeholder={"每行一条，如：\n退货运费谁出"}
            value={form.followUp}
            onChange={(e) => onChange({ followUp: e.target.value })}
          />
        </div>
        <div className="form-actions">
          <button className="btn ghost" onClick={onClose}>
            取消
          </button>
          <button className="btn primary" onClick={onSave}>
            保存草稿
          </button>
        </div>
      </div>
    </div>
  );
}

export function KbApp() {
  const [role, setRoleState] = useState<Role>(() => (localStorage.getItem(ROLE_KEY) as Role) || "ops");
  const [tab, setTab] = useState<Tab>("faqs");
  const [faqList, setFaqList] = useState<FAQItem[]>([]);
  const [faqTotal, setFaqTotal] = useState(0);
  const [draftList, setDraftList] = useState<KBDraft[]>([]);
  const [versionList, setVersionList] = useState<KBVersion[]>([]);
  const [shownSnapshots, setShownSnapshots] = useState<Record<number, boolean>>({});

  const [catFilter, setCatFilter] = useState("");
  const [qFilter, setQFilter] = useState("");
  const [draftFilter, setDraftFilter] = useState("");
  const [versionFilter, setVersionFilter] = useState("");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);

  const [toastMsg, setToastMsg] = useState<{ text: string; isErr: boolean } | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  // 自动刷新使用 ref 读取「最新」筛选条件，避免定时器闭包拿到初始空值
  const filtersRef = useRef({ catFilter, qFilter, draftFilter, versionFilter });
  filtersRef.current = { catFilter, qFilter, draftFilter, versionFilter };

  const toast = (text: string, isErr = false) => {
    setToastMsg({ text, isErr });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastMsg(null), 3500);
  };

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  // ================= 数据加载 =================
  const loadFAQs = async (category?: string, q?: string) => {
    const data = await fetchFAQs(category || undefined, q || undefined);
    setFaqList(data.faqs);
    setFaqTotal(data.total);
  };

  const loadDrafts = async (status?: string) => {
    setDraftList(await fetchDrafts(status));
  };

  const loadVersions = async (faqId?: string) => {
    setVersionList(await fetchVersions(faqId, 100));
  };

  const reload = async () => {
    try {
      const f = filtersRef.current;
      await Promise.all([
        loadFAQs(f.catFilter, f.qFilter.trim()),
        loadDrafts(f.draftFilter),
        loadVersions(f.versionFilter.trim()),
      ]);
    } catch (err) {
      toast(String(err), true);
    }
  };

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void reload();
    }, 15000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ================= 表单 =================
  const openForm = (faq?: FAQItem) => {
    setEditingId(faq?.id ?? null);
    setForm(
      faq
        ? {
            question: faq.standard_question,
            category: faq.category as FAQPayload["category"],
            risk: faq.risk_level as FAQPayload["risk_level"],
            variants: faq.variants.join("\n"),
            answer: faq.answer,
            followUp: faq.follow_up.join("\n"),
          }
        : EMPTY_FORM,
    );
    setFormOpen(true);
  };

  const closeForm = () => {
    setFormOpen(false);
    setEditingId(null);
  };

  const collectForm = (): FAQPayload | null => {
    const question = form.question.trim();
    const answer = form.answer.trim();
    if (!question) {
      toast("标准问法不能为空", true);
      return null;
    }
    if (!answer) {
      toast("答案不能为空", true);
      return null;
    }
    return {
      category: form.category,
      standard_question: question,
      variants: form.variants
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
      answer,
      risk_level: form.risk,
      follow_up: form.followUp
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    };
  };

  const saveForm = async () => {
    const payload = collectForm();
    if (!payload) return;
    try {
      if (editingId) {
        await updateFAQ(editingId, payload, role);
        toast(`已保存「${editingId}」变更草稿，去「草稿审批」提交审核后生效`);
      } else {
        const r = await createFAQ(payload, role);
        toast(`已新建 ${r.faq_id} 草稿，去「草稿审批」提交审核后生效`);
      }
      closeForm();
      await reload();
    } catch (err) {
      toast(`保存失败：${String(err)}`, true);
    }
  };

  // ================= 操作 =================
  const onFaqEdit = (faq: FAQItem) => openForm(faq);

  const onFaqDelete = async (id: string) => {
    try {
      if (!window.confirm(`确认删除 ${id}？将生成删除草稿，经审批后生效。`)) return;
      const r = await deleteFAQ(id, role);
      toast(`已生成删除草稿 #${r.draft_id}，待审批`);
      await reload();
    } catch (err) {
      toast(String(err), true);
    }
  };

  const onDraftAction = async (act: "submit" | "approve" | "reject" | "drop", id: number) => {
    try {
      if (act === "submit") {
        await submitDraft(id);
        toast(`草稿 #${id} 已提交审核`);
      } else if (act === "approve") {
        if (!window.confirm(`确认通过草稿 #${id}？将立即生效（faq.json 落盘 + 热更新 + 记版本）。`)) return;
        const r = await approveDraft(id, role);
        toast(`草稿 #${id} 已生效（${r.action} ${r.faq_id}）`);
      } else if (act === "reject") {
        const reason = window.prompt("驳回原因（可留空）：", "");
        if (reason === null) return;
        await rejectDraft(id, role, reason || undefined);
        toast(`草稿 #${id} 已驳回`);
      } else if (act === "drop") {
        if (!window.confirm(`确认撤销草稿 #${id}？`)) return;
        await deleteDraft(id);
        toast(`草稿 #${id} 已撤销`);
      }
      await reload();
    } catch (err) {
      toast(String(err), true);
    }
  };

  const onVersionRollback = async (id: number) => {
    const v = versionList.find((x) => x.id === id);
    const label = v ? `${v.faq_id} · ${v.action} · ${v.created_at}` : `#${id}`;
    if (!window.confirm(`确认回滚到版本「${label}」？\n将生成变更草稿并自动提交审核，主管审批通过后生效。`)) return;
    try {
      const r = await rollbackVersion(id, role);
      toast(`已基于版本 #${id} 生成回滚草稿 #${r.draft_id}（${r.action} ${r.faq_id}）并提交审核`);
      setTab("drafts");
      await reload();
    } catch (err) {
      toast(String(err), true);
    }
  };

  const toggleSnapshot = (id: number) => {
    setShownSnapshots((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const changeRole = (next: Role) => {
    setRoleState(next);
    localStorage.setItem(ROLE_KEY, next);
    toast(next === "approver" ? "已切换为「主管（审批）」角色" : "已切换为「运营（编辑）」角色");
    void loadDrafts(draftFilter);
  };

  const rebuild = async () => {
    try {
      const r = await rebuildKB();
      toast(`热更新完成：${r.faqs} 条 FAQ，索引版本 v${r.version}`);
    } catch (err) {
      toast(String(err), true);
    }
  };

  const pendingCount = draftList.filter((d) => d.status === "pending").length;

  return (
    <>
      <TopBar role={role} onRole={changeRole} onRebuild={() => void rebuild()} onRefresh={() => void reload()} />
      <div className="wrap">
        <Cards faqTotal={faqTotal} drafts={draftList} versions={versionList} />
        <div className="tabs">
          <button className={tab === "faqs" ? "active" : ""} onClick={() => setTab("faqs")}>
            FAQ 列表
          </button>
          <button className={tab === "drafts" ? "active" : ""} onClick={() => setTab("drafts")}>
            草稿审批 <span>{pendingCount ? `(${pendingCount})` : ""}</span>
          </button>
          <button className={tab === "versions" ? "active" : ""} onClick={() => setTab("versions")}>
            版本历史
          </button>
        </div>

        {tab === "faqs" && (
          <div className="panel">
            <div className="panel-head">
              <h2>FAQ 列表（共 {faqTotal} 条）</h2>
              <div className="spacer" />
              <div className="toolbar">
                <select
                  value={catFilter}
                  onChange={(e) => {
                    setCatFilter(e.target.value);
                    void loadFAQs(e.target.value, qFilter.trim());
                  }}
                >
                  <option value="">全部分类</option>
                  <option value="aftersales">售后</option>
                  <option value="presales">售前</option>
                  <option value="transaction">交易</option>
                  <option value="account">账号</option>
                </select>
                <input
                  placeholder="搜索标准问法 / 变体 / 答案…"
                  value={qFilter}
                  onChange={(e) => setQFilter(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void loadFAQs(catFilter, qFilter.trim());
                  }}
                />
                <button className="btn primary" onClick={() => openForm()}>
                  ＋ 新建 FAQ
                </button>
              </div>
            </div>
            <FaqTable faqs={faqList} onEdit={onFaqEdit} onDelete={(id) => void onFaqDelete(id)} />
            <div className="tip">
              操作说明：新建 / 编辑 / 删除都会生成「草稿」，提交审核后由主管审批，通过即生效（faq.json 落盘 + 索引热更新 +
              记版本）。
            </div>
          </div>
        )}

        {tab === "drafts" && (
          <div className="panel">
            <div className="panel-head">
              <h2>草稿审批流</h2>
              <div className="spacer" />
              <div className="toolbar">
                <select
                  value={draftFilter}
                  onChange={(e) => {
                    setDraftFilter(e.target.value);
                    void loadDrafts(e.target.value);
                  }}
                >
                  <option value="">全部状态</option>
                  <option value="draft">草稿</option>
                  <option value="pending">待审</option>
                  <option value="rejected">已驳回</option>
                  <option value="published">已生效</option>
                </select>
              </div>
            </div>
            <DraftTable
              drafts={draftList}
              role={role}
              onSubmit={(id) => void onDraftAction("submit", id)}
              onApprove={(id) => void onDraftAction("approve", id)}
              onReject={(id) => void onDraftAction("reject", id)}
              onDrop={(id) => void onDraftAction("drop", id)}
            />
            <div className="tip">
              流程：草稿 → 提交审核 → 主管通过（生效）/ 驳回（可改后重提）。「主管（审批）」角色可执行通过 / 驳回。
            </div>
          </div>
        )}

        {tab === "versions" && (
          <div className="panel">
            <div className="panel-head">
              <h2>版本历史（每次生效记一条，含完整快照）</h2>
              <div className="spacer" />
              <div className="toolbar">
                <input
                  placeholder="按 FAQ ID 过滤，如 faq_001"
                  style={{ width: 200 }}
                  value={versionFilter}
                  onChange={(e) => setVersionFilter(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void loadVersions(versionFilter.trim());
                  }}
                />
              </div>
            </div>
            <VersionTable
              versions={versionList}
              shown={shownSnapshots}
              onToggleSnapshot={toggleSnapshot}
              onRollback={(id) => void onVersionRollback(id)}
            />
          </div>
        )}

        <div className="error" style={toastMsg ? { color: toastMsg.isErr ? "#EF4444" : "#16A34A" } : undefined}>
          {toastMsg?.text}
        </div>
      </div>

      {formOpen && (
        <FaqFormModal
          editingId={editingId}
          form={form}
          onChange={(patch) => setForm((prev) => ({ ...prev, ...patch }))}
          onClose={closeForm}
          onSave={() => void saveForm()}
        />
      )}
    </>
  );
}

createRoot(document.getElementById("app") as HTMLElement).render(<KbApp />);
