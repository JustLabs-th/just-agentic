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
export type MessageRole = "user" | "assistant" | "system" | "tool_call";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  agent?: string;
  intent?: string;
  confidence?: number;
  image?: string;           // base64 data URL for vision messages
  toolCall?: ToolCallEvent; // for role="tool_call" rows
}

// ── SSE events from FastAPI ───────────────────────────────────────────────────
export type SSEEventType =
  | "thread_id"
  | "agent_switch"
  | "tool_call"
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
  // tool_call
  tool?: string;
  input?: Record<string, unknown>;
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

export interface ToolCallEvent {
  tool: string;
  input: Record<string, unknown>;
  agent: string;
}

export interface ApprovalRequest {
  thread_id: string;
  agent: string;
  intent: string;
  action: string;
}
