"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, CheckCircle2, Plus, Save, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { EmptyState, ErrorState, LoadingState } from "@/components/FeedbackState";
import { Pagination } from "@/components/Pagination";
import {
  archiveKnowledgeEntry,
  createKnowledgeEntry,
  listKnowledgeEntries,
  publishKnowledgeEntry,
  updateKnowledgeEntry,
} from "@/lib/knowledgeApi";
import { knowledgeStatusLabel } from "@/lib/labels";
import type { KnowledgeEntry, KnowledgeEntryStatus } from "@/types/domain";

const PAGE_SIZE = 5;

const statusFilters: Array<{ value: KnowledgeEntryStatus | ""; label: string }> = [
  { value: "", label: "Усі статуси" },
  { value: "draft", label: "Чернетки" },
  { value: "published", label: "Опубліковані" },
  { value: "archived", label: "Архів" },
];

type EditorState = {
  title: string;
  description: string;
  source_url: string;
  tags: string;
  status: KnowledgeEntryStatus;
};

const emptyEditor: EditorState = {
  title: "",
  description: "",
  source_url: "",
  tags: "",
  status: "draft",
};

function tagsToText(tags: string[]): string {
  return tags.join(", ");
}

function parseTags(value: string): string[] {
  return value
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function toEditor(entry: KnowledgeEntry): EditorState {
  return {
    title: entry.title,
    description: entry.answer,
    source_url: entry.source_url,
    tags: tagsToText(entry.tags),
    status: entry.status,
  };
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("uk-UA", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(new Date(value));
}

function knowledgeStatusTone(status: KnowledgeEntryStatus): string {
  if (status === "published") return "success";
  if (status === "archived") return "neutral";
  return "warning";
}

function KnowledgeStatusBadge({ status }: { status: KnowledgeEntryStatus }) {
  return <span className={`badge ${knowledgeStatusTone(status)}`}>{knowledgeStatusLabel[status]}</span>;
}

export default function KnowledgePage() {
  return (
    <AuthGuard roles={["admin"]}>
      <AppShell>
        <KnowledgeWorkspace />
      </AppShell>
    </AuthGuard>
  );
}

function KnowledgeWorkspace() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState>(emptyEditor);
  const [statusFilter, setStatusFilter] = useState<KnowledgeEntryStatus | "">("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [actionError, setActionError] = useState<string | null>(null);

  const entriesQuery = useQuery({
    queryKey: ["knowledgeEntries", statusFilter, search, offset],
    queryFn: () =>
      listKnowledgeEntries({
        statusFilter,
        search,
        limit: PAGE_SIZE,
        offset,
      }),
  });

  const entries = entriesQuery.data?.items ?? [];
  const selectedEntry = entries.find((entry) => entry.id === selectedId) ?? null;

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        title: editor.title.trim(),
        question: editor.title.trim(),
        answer: editor.description.trim(),
        source_url: editor.source_url.trim(),
        tags: parseTags(editor.tags),
        status: editor.status,
      };
      if (selectedId) {
        return updateKnowledgeEntry(selectedId, payload);
      }
      return createKnowledgeEntry(payload);
    },
    onSuccess: async (entry) => {
      setSelectedId(entry.id);
      setEditor(toEditor(entry));
      setActionError(null);
      await queryClient.invalidateQueries({ queryKey: ["knowledgeEntries"] });
    },
    onError: (err) => {
      setActionError(err instanceof Error ? err.message : "Не вдалося зберегти запис.");
    },
  });

  const publishMutation = useMutation({
    mutationFn: publishKnowledgeEntry,
    onSuccess: async (entry) => {
      setEditor(toEditor(entry));
      setActionError(null);
      await queryClient.invalidateQueries({ queryKey: ["knowledgeEntries"] });
    },
    onError: (err) => {
      setActionError(err instanceof Error ? err.message : "Не вдалося опублікувати запис.");
    },
  });

  const archiveMutation = useMutation({
    mutationFn: archiveKnowledgeEntry,
    onSuccess: async (entry) => {
      setEditor(toEditor(entry));
      setActionError(null);
      await queryClient.invalidateQueries({ queryKey: ["knowledgeEntries"] });
    },
    onError: (err) => {
      setActionError(err instanceof Error ? err.message : "Не вдалося архівувати запис.");
    },
  });

  useEffect(() => {
    setOffset(0);
  }, [statusFilter, search]);

  useEffect(() => {
    if (selectedEntry) {
      setEditor(toEditor(selectedEntry));
    }
  }, [selectedEntry]);

  function startNewEntry() {
    setSelectedId(null);
    setEditor(emptyEditor);
    setActionError(null);
  }

  function selectEntry(entry: KnowledgeEntry) {
    setSelectedId(entry.id);
    setEditor(toEditor(entry));
    setActionError(null);
  }

  function updateEditor<K extends keyof EditorState>(field: K, value: EditorState[K]) {
    setEditor((current) => ({ ...current, [field]: value }));
  }

  async function saveEntry() {
    setActionError(null);
    await saveMutation.mutateAsync();
  }

  const total = entriesQuery.data?.total ?? 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <>
      <div className="section-title">
        <div>
          <h1>База знань</h1>
        </div>
        <div className="toolbar">
          <button className="secondary-button" onClick={startNewEntry} type="button">
            <Plus size={18} />
            Новий запис
          </button>
        </div>
      </div>

      {actionError && <ErrorState message={actionError} />}

      <div className="toolbar filters-toolbar knowledge-filters">
        <select
          className="search-input"
          onChange={(event) => setStatusFilter(event.target.value as KnowledgeEntryStatus | "")}
          value={statusFilter}
        >
          {statusFilters.map((item) => (
            <option key={item.value || "all"} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <label className="knowledge-search">
          <Search size={17} />
          <input
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Пошук"
            type="search"
            value={search}
          />
        </label>
      </div>

      <div className="grid-two knowledge-grid">
        <section className="panel">
          <div className="panel-header">
            <h2>Записи</h2>
            {total > 0 && <span className="muted small">{total}</span>}
          </div>

          {entriesQuery.isLoading ? (
            <LoadingState message="Завантажуємо записи..." />
          ) : entriesQuery.isError ? (
            <ErrorState message="Не вдалося завантажити записи." onRetry={() => entriesQuery.refetch()} />
          ) : entries.length === 0 ? (
            <EmptyState message="Записів не знайдено." />
          ) : (
            <div className="ticket-list">
              {entries.map((entry) => (
                <button
                  className={entry.id === selectedId ? "ticket-row active" : "ticket-row"}
                  key={entry.id}
                  onClick={() => selectEntry(entry)}
                  type="button"
                >
                  <div className="ticket-row-top">
                    <span className="ticket-title">{entry.title}</span>
                    <KnowledgeStatusBadge status={entry.status} />
                  </div>
                  <span className="muted small ticket-description">{entry.answer}</span>
                </button>
              ))}
            </div>
          )}

          <Pagination
            currentPage={currentPage}
            disabled={entriesQuery.isFetching}
            onPageChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
            pageSize={PAGE_SIZE}
            total={total}
          />
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>{selectedId ? "Редагування" : "Новий запис"}</h2>
          </div>

          <div className="knowledge-editor">
            <div className="field">
              <label htmlFor="knowledge-title">Назва</label>
              <input
                id="knowledge-title"
                onChange={(event) => updateEditor("title", event.target.value)}
                value={editor.title}
              />
            </div>
            <div className="field">
              <label htmlFor="knowledge-description">Опис</label>
              <textarea
                id="knowledge-description"
                onChange={(event) => updateEditor("description", event.target.value)}
                value={editor.description}
              />
            </div>
            <div className="meta-grid">
              <div className="field">
                <label htmlFor="knowledge-source">Джерело</label>
                <input
                  id="knowledge-source"
                  onChange={(event) => updateEditor("source_url", event.target.value)}
                  value={editor.source_url}
                />
              </div>
              <div className="field">
                <label htmlFor="knowledge-status">Статус</label>
                <select
                  id="knowledge-status"
                  onChange={(event) => updateEditor("status", event.target.value as KnowledgeEntryStatus)}
                  value={editor.status}
                >
                  <option value="draft">Чернетка</option>
                  <option value="published">Опубліковано</option>
                  <option value="archived">Архів</option>
                </select>
              </div>
            </div>
            <div className="field">
              <label htmlFor="knowledge-tags">Теги</label>
              <input
                id="knowledge-tags"
                onChange={(event) => updateEditor("tags", event.target.value)}
                value={editor.tags}
              />
            </div>
          </div>

          <div className="toolbar">
            <button
              className="primary-button"
              disabled={saveMutation.isPending}
              onClick={saveEntry}
              type="button"
            >
              <Save size={18} />
              Зберегти
            </button>
            {selectedId && (
              <>
                <button
                  className="secondary-button"
                  disabled={publishMutation.isPending}
                  onClick={() => publishMutation.mutate(selectedId)}
                  type="button"
                >
                  <CheckCircle2 size={18} />
                  Опублікувати
                </button>
                <button
                  className="danger-button"
                  disabled={archiveMutation.isPending}
                  onClick={() => archiveMutation.mutate(selectedId)}
                  type="button"
                >
                  <Archive size={18} />
                  Архівувати
                </button>
              </>
            )}
          </div>

          {selectedEntry && (
            <div className="knowledge-meta-strip">
              <span>Оновлено: {formatDate(selectedEntry.updated_at)}</span>
              <span>Опубліковано: {formatDate(selectedEntry.published_at)}</span>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
