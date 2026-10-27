/** 知识库后台（V2.0）：FAQ CRUD + 草稿审批流 + 版本历史。角色：运营（编辑）/ 主管（审批）。 */
import {
  approveDraft,
  createFAQ,
  deleteDraft,
  deleteFAQ,
  fetchDrafts,
  fetchFAQs,
  fetchVersions,
  KB_ACTIONS,
  rejectDraft,
  submitDraft,
  updateFAQ,
  rebuildKB,
  type FAQItem,
  type FAQPayload,
  type KBDraft,
  type KBVersion,
} from "./api";

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;
const v = (id: string): string => ($(id) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value ?? "";
const setv = (id: string, val: string): void => {
  ($(id) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value = val;
};

const ROLE_KEY = "xd_kb_role";
let role: "ops" | "approver" = (localStorage.getItem(ROLE_KEY) as "ops" | "approver") || "ops";
let tab: "faqs" | "drafts" | "versions" = "faqs";
let faqList: FAQItem[] = [];
let draftList: KBDraft[] = [];
let versionList: KBVersion[] = [];
let editingId: string | null = null;

function esc(text: string | null | undefined): string {
  return (text ?? "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

let toastTimer: number | undefined;
function toast(msg: string, isErr = false): void {
  const el = $("error");
  el.textContent = msg;
  el.style.color = isErr ? "#EF4444" : "#16A34A";
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { el.textContent = ""; }, 3500);
}

function roleBadge(status: string | undefined): string {
  const map: Record<string, string> = {
    draft: '<span class="badge gray">有草稿</span>',
    pending: '<span class="badge orange">待审核</span>',
    rejected: '<span class="badge red">已驳回</span>',
  };
  return map[status ?? ""] ?? "";
}

function catZh(cat: string): string {
  const map: Record<string, string> = { aftersales: "售后", presales: "售前", transaction: "交易", account: "账号" };
  return map[cat] ?? cat;
}

function riskBadge(level: string): string {
  const map: Record<string, string> = {
    low: '<span class="badge green">低</span>',
    mid: '<span class="badge orange">中</span>',
    high: '<span class="badge red">高</span>',
  };
  return map[level] ?? level;
}

function statusBadge(status: string): string {
  const map: Record<string, string> = {
    draft: '<span class="badge gray">草稿</span>',
    pending: '<span class="badge orange">待审</span>',
    rejected: '<span class="badge red">已驳回</span>',
    published: '<span class="badge green">已生效</span>',
  };
  return map[status] ?? status;
}

// ================= 卡片统计 =================
async function renderCards(): Promise<void> {
  const data = await fetchFAQs();
  const pendingCount = draftList.filter((d) => d.status === "pending").length;
  const draftCount = draftList.filter((d) => d.status === "draft" || d.status === "rejected").length;
  const cards = $("cards");
  cards.innerHTML = "";
  const items: Array<[string, string, string, boolean?]> = [
    ["FAQ 总数", String(data.total), "已生效知识库条目"],
    ["待审核", String(pendingCount), "等待主管审批", pendingCount > 0],
    ["草稿 / 已驳回", String(draftCount), "未生效的变更"],
    ["版本记录", String(versionList.length), "审批生效的历史快照"],
  ];
  for (const [label, num, sub, warn] of items) {
    const c = document.createElement("div");
    c.className = "card";
    c.innerHTML = `<div class="num ${warn ? "warn" : ""}">${num}</div><div class="label">${label} · ${sub}</div>`;
    cards.appendChild(c);
  }
  $("pending-count").textContent = pendingCount ? `(${pendingCount})` : "";
  $("faq-total").textContent = String(data.total);
}

// ================= FAQ 列表 =================
async function renderFAQs(): Promise<void> {
  const category = v("cat-filter");
  const q = v("q-filter").trim();
  const data = await fetchFAQs(category || undefined, q || undefined);
  faqList = data.faqs;
  const tbody = $("faq-tbody");
  tbody.innerHTML = "";
  if (!faqList.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">暂无 FAQ（可调整筛选条件或新建）</td></tr>';
    return;
  }
  for (const f of faqList) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${esc(f.id)}</td>` +
      `<td><div class="q">${esc(f.standard_question)}</div></td>` +
      `<td>${catZh(f.category)}</td>` +
      `<td>${riskBadge(f.risk_level)}</td>` +
      `<td>${roleBadge(f.draft_status)}</td>` +
      `<td>` +
      `<button class="btn ghost small" data-act="edit" data-id="${esc(f.id)}">编辑</button> ` +
      `<button class="btn danger small" data-act="del" data-id="${esc(f.id)}">删除</button>` +
      `</td>`;
    tbody.appendChild(tr);
  }
}

// ================= 草稿列表 =================
async function renderDrafts(): Promise<void> {
  const status = v("draft-filter") || undefined;
  const list = await fetchDrafts(status);
  draftList = list;
  const tbody = $("draft-tbody");
  tbody.innerHTML = "";
  if (!draftList.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">暂无草稿</td></tr>';
    return;
  }
  const isApprover = role === "approver";
  for (const d of draftList) {
    const summary = d.action === "delete"
      ? `<span class="badge red">删除 ${esc(d.faq_id)}</span>`
      : `${esc(d.payload?.standard_question ?? "")}`;
    let ops = "";
    if (d.status === "draft" || d.status === "rejected") {
      ops += `<button class="btn primary small" data-act="submit" data-id="${d.id}">提交审核</button> `;
      ops += `<button class="btn ghost small" data-act="drop" data-id="${d.id}">撤销</button>`;
    } else if (d.status === "pending") {
      if (isApprover) {
        ops += `<button class="btn success small" data-act="approve" data-id="${d.id}">通过</button> `;
        ops += `<button class="btn danger small" data-act="reject" data-id="${d.id}">驳回</button>`;
      } else {
        ops = '<span class="tip">待主管审批</span>';
      }
    } else {
      ops = '<span class="tip">已生效</span>';
    }
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>#${d.id}</td>` +
      `<td>${esc(d.faq_id)}</td>` +
      `<td>${KB_ACTIONS[d.action] ?? d.action}</td>` +
      `<td>${summary}</td>` +
      `<td>${statusBadge(d.status)}</td>` +
      `<td>${ops}</td>`;
    tbody.appendChild(tr);
  }
}

// ================= 版本历史 =================
async function renderVersions(): Promise<void> {
  const faqId = v("v-faq-filter").trim() || undefined;
  const list = await fetchVersions(faqId, 100);
  versionList = list;
  const tbody = $("version-tbody");
  tbody.innerHTML = "";
  if (!versionList.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">暂无版本记录（审批生效后产生）</td></tr>';
    return;
  }
  for (const v of versionList) {
    const snapshotText = v.snapshot ? JSON.stringify(v.snapshot, null, 2) : "（无快照）";
    const actionBadge: Record<string, string> = {
      create: '<span class="badge green">新建</span>',
      update: '<span class="badge blue">编辑</span>',
      delete: '<span class="badge red">删除</span>',
    };
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${esc(v.created_at)}</td>` +
      `<td>${esc(v.faq_id)}</td>` +
      `<td>${actionBadge[v.action] ?? esc(v.action)}</td>` +
      `<td>${esc(v.operator)}</td>` +
      `<td>` +
      `<button class="btn ghost small" data-act="toggle-snap" data-id="${v.id}">查看快照</button>` +
      `<div class="versions-snapshot" id="snap-${v.id}">${esc(snapshotText)}</div>` +
      `</td>`;
    tbody.appendChild(tr);
  }
}

// ================= 表单 =================
function openForm(faq?: FAQItem): void {
  editingId = faq?.id ?? null;
  $("modal-title").textContent = faq ? `编辑 FAQ · ${faq.id}` : "新建 FAQ";
  setv("f-question", faq?.standard_question ?? "");
  setv("f-category", faq?.category ?? "aftersales");
  setv("f-risk", faq?.risk_level ?? "low");
  setv("f-variants", (faq?.variants ?? []).join("\n"));
  setv("f-answer", faq?.answer ?? "");
  setv("f-followup", (faq?.follow_up ?? []).join("\n"));
  $("modal").classList.add("show");
}

function closeForm(): void {
  $("modal").classList.remove("show");
  editingId = null;
}

function collectForm(): FAQPayload | null {
  const question = v("f-question").trim();
  const answer = v("f-answer").trim();
  if (!question) { toast("标准问法不能为空", true); return null; }
  if (!answer) { toast("答案不能为空", true); return null; }
  return {
    category: v("f-category") as FAQPayload["category"],
    standard_question: question,
    variants: v("f-variants").split("\n").map((s) => s.trim()).filter(Boolean),
    answer,
    risk_level: v("f-risk") as FAQPayload["risk_level"],
    follow_up: v("f-followup").split("\n").map((s) => s.trim()).filter(Boolean),
  };
}

async function saveForm(): Promise<void> {
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
}

// ================= 操作分发 =================
async function onFaqAction(act: string, id: string): Promise<void> {
  try {
    if (act === "edit") {
      const f = faqList.find((x) => x.id === id);
      if (f) openForm(f);
    } else if (act === "del") {
      if (!window.confirm(`确认删除 ${id}？将生成删除草稿，经审批后生效。`)) return;
      const r = await deleteFAQ(id, role);
      toast(`已生成删除草稿 #${r.draft_id}，待审批`);
      await reload();
    }
  } catch (err) {
    toast(String(err), true);
  }
}

async function onDraftAction(act: string, idStr: string): Promise<void> {
  const id = Number(idStr);
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
}

async function reload(): Promise<void> {
  try {
    await Promise.all([renderCards(), renderFAQs(), renderDrafts(), renderVersions()]);
    $("error").textContent = "";
  } catch (err) {
    toast(String(err), true);
  }
}

function switchTab(next: "faqs" | "drafts" | "versions"): void {
  tab = next;
  $("tab-faqs").classList.toggle("active", tab === "faqs");
  $("tab-drafts").classList.toggle("active", tab === "drafts");
  $("tab-versions").classList.toggle("active", tab === "versions");
  $("panel-faqs").style.display = tab === "faqs" ? "" : "none";
  $("panel-drafts").style.display = tab === "drafts" ? "" : "none";
  $("panel-versions").style.display = tab === "versions" ? "" : "none";
}

// ================= 事件绑定 =================
function bind(): void {
  $("role").addEventListener("change", (e) => {
    role = (e.target as HTMLSelectElement).value as "ops" | "approver";
    localStorage.setItem(ROLE_KEY, role);
    toast(role === "approver" ? "已切换为「主管（审批）」角色" : "已切换为「运营（编辑）」角色");
    void renderDrafts();
  });

  $("refresh").addEventListener("click", () => void reload());
  $("rebuild").addEventListener("click", async () => {
    try {
      const r = await rebuildKB();
      toast(`热更新完成：${r.faqs} 条 FAQ，索引版本 v${r.version}`);
    } catch (err) {
      toast(String(err), true);
    }
  });

  $("tab-faqs").addEventListener("click", () => switchTab("faqs"));
  $("tab-drafts").addEventListener("click", () => switchTab("drafts"));
  $("tab-versions").addEventListener("click", () => switchTab("versions"));

  $("btn-new").addEventListener("click", () => openForm());
  $("btn-cancel").addEventListener("click", closeForm);
  $("btn-save").addEventListener("click", () => void saveForm());
  $("modal-mask").addEventListener("click", (e) => {
    if (e.target === $("modal-mask")) closeForm();
  });

  $("cat-filter").addEventListener("change", () => void renderFAQs());
  $("q-filter").addEventListener("keydown", (e) => { if (e.key === "Enter") void renderFAQs(); });
  $("draft-filter").addEventListener("change", () => void renderDrafts());
  $("v-faq-filter").addEventListener("keydown", (e) => { if (e.key === "Enter") void renderVersions(); });

  $("faq-tbody").addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest("button[data-act]") as HTMLButtonElement | null;
    if (btn) void onFaqAction(btn.dataset.act!, btn.dataset.id!);
  });
  $("draft-tbody").addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest("button[data-act]") as HTMLButtonElement | null;
    if (btn) void onDraftAction(btn.dataset.act!, btn.dataset.id!);
  });
  $("version-tbody").addEventListener("click", (e) => {
    const btn = (e.target as HTMLElement).closest("button[data-act]") as HTMLButtonElement | null;
    if (btn && btn.dataset.act === "toggle-snap") {
      const snap = document.getElementById(`snap-${btn.dataset.id}`) as HTMLDivElement;
      if (snap) snap.classList.toggle("show");
    }
  });
}

// ================= 启动 =================
function init(): void {
  setv("role", role);
  bind();
  void reload();
  window.setInterval(() => { if (document.visibilityState === "visible") void reload(); }, 15000);
}

init();
