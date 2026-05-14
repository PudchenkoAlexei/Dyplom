import { apiRequest, audioUrl, messageAudioUrl } from "@/lib/api";
import type {
  Category,
  Department,
  OperatorTicketPage,
  Priority,
  Ticket,
  TicketStatus,
} from "@/types/domain";

export interface DraftTicketResponse {
  ticket: Ticket;
  transcript_text: string;
}

export interface OperatorTicketFilters {
  statusFilter?: TicketStatus | "";
  assignedToMe?: "" | "true" | "false";
  categoryId?: string;
  sortBy?: "created_desc" | "category";
  limit?: number;
  offset?: number;
}

export function ticketAudioUrl(ticketId: string): string {
  return audioUrl(ticketId);
}

export function ticketMessageAudioUrl(ticketId: string, messageId: string): string {
  return messageAudioUrl(ticketId, messageId);
}

export async function createDraftFromAudio(formData: FormData): Promise<DraftTicketResponse> {
  return apiRequest<DraftTicketResponse>("/tickets/draft-audio", {
    method: "POST",
    formData,
  });
}

export async function createDraftFromBrowserTranscript(formData: FormData): Promise<DraftTicketResponse> {
  return apiRequest<DraftTicketResponse>("/tickets/draft-browser-transcript", {
    method: "POST",
    formData,
  });
}

export async function listMyTickets(): Promise<Ticket[]> {
  return apiRequest<Ticket[]>("/tickets/my");
}

export async function getRequesterTicket(ticketId: string): Promise<Ticket> {
  return apiRequest<Ticket>(`/tickets/${ticketId}`);
}

export async function submitTicket(ticketId: string): Promise<Ticket> {
  return apiRequest<Ticket>(`/tickets/${ticketId}/submit`, {
    method: "POST",
  });
}

export async function deleteRequesterTicket(ticketId: string): Promise<void> {
  await apiRequest<unknown>(`/tickets/${ticketId}`, { method: "DELETE" });
}

export async function listCategories(): Promise<Category[]> {
  return apiRequest<Category[]>("/categories");
}

export async function listDepartments(): Promise<Department[]> {
  return apiRequest<Department[]>("/departments");
}

export async function listOperatorTickets({
  statusFilter,
  assignedToMe,
  categoryId,
  sortBy = "created_desc",
  limit = 20,
  offset = 0,
}: OperatorTicketFilters): Promise<OperatorTicketPage> {
  const params = new URLSearchParams();
  if (statusFilter) params.set("status_filter", statusFilter);
  if (assignedToMe) params.set("assigned_to_me", assignedToMe);
  if (categoryId) params.set("category_id", categoryId);
  params.set("sort_by", sortBy);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const suffix = params.toString() ? `?${params}` : "";
  return apiRequest<OperatorTicketPage>(`/operator/tickets${suffix}`);
}

export async function getOperatorTicket(ticketId: string): Promise<Ticket> {
  return apiRequest<Ticket>(`/operator/tickets/${ticketId}`);
}

export async function claimOperatorTicket(ticketId: string): Promise<Ticket> {
  return apiRequest<Ticket>(`/operator/tickets/${ticketId}/claim`, { method: "POST" });
}

export async function deleteOperatorTicket(ticketId: string): Promise<void> {
  await apiRequest<unknown>(`/operator/tickets/${ticketId}`, { method: "DELETE" });
}

export async function updateOperatorClassification(
  ticketId: string,
  payload: {
    category_id: string;
    department_id: string;
    priority: Priority;
  },
): Promise<Ticket> {
  return apiRequest<Ticket>(`/operator/tickets/${ticketId}/classification`, {
    method: "PATCH",
    body: payload,
  });
}

export async function addOperatorMessage(ticketId: string, message: string): Promise<Ticket> {
  return apiRequest<Ticket>(`/operator/tickets/${ticketId}/messages`, {
    method: "POST",
    body: { message },
  });
}

export async function addOperatorVoiceMessage(ticketId: string, formData: FormData): Promise<Ticket> {
  return apiRequest<Ticket>(`/operator/tickets/${ticketId}/voice-message`, {
    method: "POST",
    formData,
  });
}

export async function transcribeTicketMessage(ticketId: string, messageId: string): Promise<Ticket> {
  return apiRequest<Ticket>(`/tickets/${ticketId}/messages/${messageId}/transcribe`, {
    method: "POST",
  });
}

export async function closeOperatorTicket(ticketId: string): Promise<Ticket> {
  return apiRequest<Ticket>(`/operator/tickets/${ticketId}/close`, { method: "POST" });
}
