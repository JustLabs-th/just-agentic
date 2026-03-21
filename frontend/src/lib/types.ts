// ── Auth ──────────────────────────────────────────────────────────────────────
export interface LoginResponse {
  access_token: string;
  user_id: string;
  role: string;
  department: string;
  clearance_level: number;
  allowed_tools: string[];
}

export interface UserSession extends LoginResponse {}

// ── Chat ──────────────────────────────────────────────────────────────────────
export type MessageRole = "user" | "assistant" | "system";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  agent?: string;    // which agent produced this (backend | devops | qa)
  intent?: string;
  confidence?: number;
}

// ── SSE events from FastAPI ───────────────────────────────────────────────────
export type SSEEventType =
  | "thread_id"
  | "agent_switch"
  | "message"
  | "approval_required"
  | "permission_denied"
  | "done"
  | "error";

export interface SSEEvent {
  type: SSEEventType;
  // thread_id
  thread_id?: string;
  // agent_switch
  agent?: string;
  intent?: string;
  confidence?: number;
  // message
  content?: string;
  role?: string;
  // approval_required
  action?: string;
  // permission_denied / error
  error?: string;
  // done
  status?: string;
  final_answer?: string;
}

export interface ApprovalRequest {
  thread_id: string;
  agent: string;
  intent: string;
  action: string;
}
