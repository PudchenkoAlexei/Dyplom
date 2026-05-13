export type UserRole = "student" | "teacher" | "operator" | "admin";
export type TicketStatus =
  | "draft"
  | "submitted"
  | "classified"
  | "in_progress"
  | "waiting_user"
  | "answered"
  | "closed";
export type Priority = "low" | "medium" | "high";

export interface User {
  id: string;
  email: string;
  full_name: string;
  student_group: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Department {
  id: string;
  name: string;
  description: string | null;
  contact_url: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Category {
  id: string;
  name: string;
  description: string | null;
  default_department_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TicketAudio {
  id: string;
  mime_type: string;
  size_bytes: number;
  duration_seconds: number | null;
  created_at: string;
  updated_at: string;
}

export interface TicketTranscript {
  id: string;
  raw_text: string;
  edited_text: string | null;
  stt_model: string;
  language: string | null;
  created_at: string;
  updated_at: string;
}

export interface TicketMessage {
  id: string;
  sender_id: string;
  message: string;
  created_at: string;
  updated_at: string;
}

export interface TicketEvent {
  id: string;
  actor_id: string | null;
  event_type: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  created_at: string;
}

export interface Ticket {
  id: string;
  author_id: string;
  status: TicketStatus;
  priority: Priority | null;
  title: string | null;
  edited_text: string | null;
  model_reason: string | null;
  model_confidence: number | null;
  closed_at: string | null;
  assigned_operator_id: string | null;
  category: Category | null;
  department: Department | null;
  audio: TicketAudio | null;
  transcript: TicketTranscript | null;
  messages: TicketMessage[];
  events: TicketEvent[];
  created_at: string;
  updated_at: string;
  author?: User;
  assigned_operator?: User | null;
}

export interface OperatorTicketPage {
  items: Ticket[];
  total: number;
  limit: number;
  offset: number;
}
