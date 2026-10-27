/** 后端 API 封装：契约对齐 backend/app/models/schemas.py。 */

export interface QuickChip {
  label: string;
  value: string;
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

export interface ChatInitResponse {
  session_id: string;
  visitor_token: string;
  expires_in: number;
  brand_name: string;
  quick_chips: QuickChip[];
  history: HistoryMessage[];
  status: string;
}

export interface ChatInitPayload {
  session_id?: string;
  user_id?: string;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`API ${path} 失败(${resp.status}): ${text.slice(0, 120)}`);
  }
  return resp.json() as Promise<T>;
}

export async function chatInit(payload: ChatInitPayload): Promise<ChatInitResponse> {
  return post<ChatInitResponse>("/api/v1/chat/init", payload);
}

export async function sendFeedback(payload: {
  session_id: string;
  message_id?: string;
  value: "up" | "down";
  query?: string;
  context?: string;
  answer?: string;
}): Promise<{ ok: boolean; feedback_id?: number }> {
  return post("/api/v1/feedback", payload);
}

export async function bindSession(payload: {
  anonymous_session_id: string;
  user_id: string;
}): Promise<{ ok: boolean; session_id: string; user_id: string }> {
  return post("/api/v1/session/bind", payload);
}

export async function manualHandover(payload: {
  session_id: string;
  visitor_token: string;
  contact?: string;
}): Promise<{ ok: boolean; queue_id?: number; message?: string }> {
  return post("/api/v1/handover", payload);
}

// ---------------- V1.5 运营 / 坐席 / 排队 ----------------

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(path);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`API ${path} 失败(${resp.status}): ${text.slice(0, 120)}`);
  }
  return resp.json() as Promise<T>;
}

async function del<T>(path: string): Promise<T> {
  const resp = await fetch(path, { method: "DELETE" });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`API ${path} 失败(${resp.status}): ${text.slice(0, 120)}`);
  }
  return resp.json() as Promise<T>;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`API ${path} 失败(${resp.status}): ${text.slice(0, 120)}`);
  }
  return resp.json() as Promise<T>;
}

export interface QueueStatus {
  queue_id: number;
  position: number | null;
  ahead: number | null;
  status: string;
  created_at: string;
}

export interface OpsStats {
  total_sessions: number;
  agent_resolved: number;
  handover: number;
  auto_rate: number;
  handover_rate: number;
  feedback_total: number;
  feedback_up: number;
  feedback_down: number;
  up_rate: number | null;
  csat_total?: number;
  csat_avg?: number | null;
  csat_dist?: Record<string, number>;
}

export interface RuntimeState {
  mode: "auto" | "handover" | "off";
  gray_percent: number;
  kill_switch: boolean;
}

export interface HandoverItem {
  id: number;
  session_id: string;
  summary: string;
  contact: string | null;
  status: string;
  created_at: string;
}

export interface BadCaseItem {
  id: number;
  session_id: string;
  message_id: string | null;
  value: string;
  query: string | null;
  context: string | null;
  answer: string | null;
  created_at: string;
  status?: "open" | "resolved" | "ignored";
  note?: string;
}

export function fetchQueueStatus(queueId: number): Promise<QueueStatus> {
  return get<QueueStatus>(`/api/v1/ops/queue/status?queue_id=${queueId}`);
}

export function fetchStats(): Promise<OpsStats> {
  return get<OpsStats>("/api/v1/ops/stats");
}

export function fetchHandovers(status = "waiting"): Promise<HandoverItem[]> {
  return get<HandoverItem[]>(`/api/v1/ops/handovers?status=${status}`);
}

export function fetchBadCases(limit = 20): Promise<BadCaseItem[]> {
  return get<BadCaseItem[]>(`/api/v1/ops/badcases?limit=${limit}`);
}

export async function completeHandover(queueId: number): Promise<{ ok: boolean; queue_id: number }> {
  return post(`/api/v1/ops/handovers/${queueId}/complete`, {});
}

// ---------------- V2.0 运行控制（Kill Switch + 灰度） ----------------
export function fetchRuntime(): Promise<RuntimeState> {
  return get<RuntimeState>("/api/v1/ops/runtime");
}

export function updateRuntime(patch: Partial<Pick<RuntimeState, "mode" | "gray_percent">>): Promise<RuntimeState> {
  return put<RuntimeState>("/api/v1/ops/runtime", patch);
}

// ---------------- V2.0 Bad Case 管理 ----------------
export function setBadCaseStatus(
  feedbackId: number,
  status: "open" | "resolved" | "ignored",
  note = "",
): Promise<{ ok: boolean; feedback_id: number; status: string; note: string }> {
  return post(`/api/v1/ops/badcases/${feedbackId}/status`, { status, note });
}

// ---------------- V2.0 CSAT 满意度 ----------------
export function submitCsat(payload: {
  session_id: string;
  visitor_token: string;
  rating: number;
  comment?: string;
}): Promise<{ ok: boolean; rating: number }> {
  return post("/api/v1/csat", payload);
}

export function fetchCsat(): Promise<{ csat_total: number; csat_avg: number | null; csat_dist: Record<string, number> }> {
  return get("/api/v1/ops/csat");
}

// ---------------- V2.0 坐席 AI Copilot ----------------

export interface CopilotTicket {
  user_intent?: string;
  order_info?: string;
  bot_answered?: string;
  issue?: string;
}

export interface CopilotPayload {
  ticket?: CopilotTicket;
  templates?: string[];
}

export function fetchCopilot(queueId: number): Promise<{ queue_id: number; session_id: string; copilot: CopilotPayload }> {
  return get(`/api/v1/ops/copilot/${queueId}`);
}

export function generateTemplates(queueId: number): Promise<{ queue_id: number; templates: string[] }> {
  return post(`/api/v1/ops/copilot/templates?queue_id=${queueId}`, {});
}

export function copilotQuery(
  queueId: number,
  action: "logistics" | "order" | "refund",
): Promise<{ action: string; result: string; mock: boolean }> {
  return post(`/api/v1/ops/copilot/query?queue_id=${queueId}&action=${action}`, {});
}

// ---------------- V2.0 知识库后台（FAQ CRUD + 草稿审批流 + 版本历史） ----------------

export interface FAQItem {
  id: string;
  category: string;
  standard_question: string;
  variants: string[];
  answer: string;
  risk_level: string;
  follow_up: string[];
  draft_id?: number;
  draft_status?: string;
  draft_action?: string;
}

export interface FAQPayload {
  category: "aftersales" | "presales" | "transaction" | "account";
  standard_question: string;
  variants: string[];
  answer: string;
  risk_level: "low" | "mid" | "high";
  follow_up: string[];
}

export interface FAQListResponse {
  total: number;
  categories: Record<string, number>;
  faqs: FAQItem[];
}

export interface KBDraft {
  id: number;
  faq_id: string;
  action: "create" | "update" | "delete";
  payload: FAQPayload | null;
  status: "draft" | "pending" | "rejected" | "published";
  created_by: string;
  reviewed_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface KBVersion {
  id: number;
  faq_id: string;
  action: string;
  snapshot: FAQPayload | null;
  operator: string;
  created_at: string;
}

export const KB_CATEGORIES = [
  { key: "aftersales", zh: "售后" },
  { key: "presales", zh: "售前" },
  { key: "transaction", zh: "交易" },
  { key: "account", zh: "账号" },
] as const;

export const KB_RISK_LEVELS = [
  { key: "low", zh: "低" },
  { key: "mid", zh: "中" },
  { key: "high", zh: "高" },
] as const;

export const KB_DRAFT_STATUS: Record<string, string> = {
  draft: "草稿",
  pending: "待审",
  rejected: "已驳回",
  published: "已生效",
};

export const KB_ACTIONS: Record<string, string> = {
  create: "新建",
  update: "编辑",
  delete: "删除",
};

export function fetchFAQs(category?: string, q?: string): Promise<FAQListResponse> {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (q) params.set("q", q);
  const qs = params.toString();
  return get<FAQListResponse>(`/api/v1/kb/faqs${qs ? `?${qs}` : ""}`);
}

export function fetchFAQ(faqId: string): Promise<FAQItem> {
  return get<FAQItem>(`/api/v1/kb/faqs/${faqId}`);
}

export function createFAQ(faq: FAQPayload, createdBy = "ops"): Promise<{ draft_id: number; faq_id: string; status: string }> {
  return post("/api/v1/kb/faqs", { faq, created_by: createdBy });
}

export function updateFAQ(faqId: string, faq: FAQPayload, createdBy = "ops"): Promise<{ draft_id: number; faq_id: string; status: string }> {
  return put(`/api/v1/kb/faqs/${faqId}`, { faq, created_by: createdBy });
}

export function deleteFAQ(faqId: string, createdBy = "ops"): Promise<{ draft_id: number; faq_id: string; status: string }> {
  return del(`/api/v1/kb/faqs/${faqId}?created_by=${createdBy}`);
}

export function fetchDrafts(status?: string): Promise<KBDraft[]> {
  return get<KBDraft[]>(`/api/v1/kb/drafts${status ? `?status=${status}` : ""}`);
}

export function submitDraft(draftId: number): Promise<{ ok: boolean; draft_id: number; status: string }> {
  return post(`/api/v1/kb/drafts/${draftId}/submit`, {});
}

export function approveDraft(draftId: number, reviewedBy = "ops"): Promise<{ ok: boolean; faq_id: string; action: string }> {
  return post(`/api/v1/kb/drafts/${draftId}/approve`, { reviewed_by: reviewedBy });
}

export function rejectDraft(draftId: number, reviewedBy = "ops", reason?: string): Promise<{ ok: boolean; draft_id: number; status: string }> {
  return post(`/api/v1/kb/drafts/${draftId}/reject`, { reviewed_by: reviewedBy, reason: reason || null });
}

export function deleteDraft(draftId: number): Promise<{ ok: boolean; draft_id: number }> {
  return del(`/api/v1/kb/drafts/${draftId}`);
}

export function fetchVersions(faqId?: string, limit = 50): Promise<KBVersion[]> {
  const params = new URLSearchParams();
  if (faqId) params.set("faq_id", faqId);
  params.set("limit", String(limit));
  return get<KBVersion[]>(`/api/v1/kb/versions?${params.toString()}`);
}

export function rollbackVersion(
  versionId: number,
  createdBy = "ops",
): Promise<{ ok: boolean; draft_id: number; faq_id: string; action: string; status: string; message: string }> {
  return post(`/api/v1/kb/versions/${versionId}/rollback`, { created_by: createdBy });
}

export function rebuildKB(): Promise<{ ok: boolean; faqs: number; version: number }> {
  return post("/api/v1/kb/rebuild", {});
}
