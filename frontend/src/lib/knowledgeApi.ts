import { apiRequest } from "@/lib/api";
import type {
  KnowledgeEntry,
  KnowledgeEntryPage,
  KnowledgeEntryStatus,
} from "@/types/domain";

export interface KnowledgeEntryFilters {
  statusFilter?: KnowledgeEntryStatus | "";
  search?: string;
  limit?: number;
  offset?: number;
}

export interface KnowledgeEntryPayload {
  title: string;
  question: string;
  answer: string;
  source_url: string;
  tags: string[];
  status?: KnowledgeEntryStatus;
}

export async function listKnowledgeEntries({
  statusFilter,
  search,
  limit = 20,
  offset = 0,
}: KnowledgeEntryFilters): Promise<KnowledgeEntryPage> {
  const params = new URLSearchParams();
  if (statusFilter) params.set("status_filter", statusFilter);
  if (search) params.set("search", search);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const suffix = params.toString() ? `?${params}` : "";
  return apiRequest<KnowledgeEntryPage>(`/admin/knowledge${suffix}`);
}

export async function createKnowledgeEntry(payload: KnowledgeEntryPayload): Promise<KnowledgeEntry> {
  return apiRequest<KnowledgeEntry>("/admin/knowledge", {
    method: "POST",
    body: { ...payload },
  });
}

export async function updateKnowledgeEntry(
  entryId: string,
  payload: Partial<KnowledgeEntryPayload>,
): Promise<KnowledgeEntry> {
  return apiRequest<KnowledgeEntry>(`/admin/knowledge/${entryId}`, {
    method: "PATCH",
    body: { ...payload },
  });
}

export async function publishKnowledgeEntry(entryId: string): Promise<KnowledgeEntry> {
  return apiRequest<KnowledgeEntry>(`/admin/knowledge/${entryId}/publish`, {
    method: "POST",
  });
}

export async function archiveKnowledgeEntry(entryId: string): Promise<KnowledgeEntry> {
  return apiRequest<KnowledgeEntry>(`/admin/knowledge/${entryId}/archive`, {
    method: "POST",
  });
}
