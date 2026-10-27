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
