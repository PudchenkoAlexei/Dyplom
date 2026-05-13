import { apiRequest, audioUrl } from "@/lib/api";
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
  limit?: number;
  offset?: number;
}

export function ticketAudioUrl(ticketId: string): string {
  return audioUrl(ticketId);
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
  limit = 20,
  offset = 0,
}: OperatorTicketFilters): Promise<OperatorTicketPage> {
  const params = new URLSearchParams();
  if (statusFilter) params.set("status_filter", statusFilter);
  if (assignedToMe) params.set("assigned_to_me", assignedToMe);
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

export async function closeOperatorTicket(ticketId: string): Promise<Ticket> {
  return apiRequest<Ticket>(`/operator/tickets/${ticketId}/close`, { method: "POST" });
}
