"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { EmptyState, ErrorState, LoadingState } from "@/components/FeedbackState";
import { OperatorTicketDetail } from "@/components/OperatorTicketDetail";
import { Pagination } from "@/components/Pagination";
import { ProfileRequired } from "@/components/ProfileRequired";
import { requesterSummary } from "@/components/RequesterMeta";
import { PriorityBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { isProfileComplete, profileIssues } from "@/lib/profile";
import {
  claimOperatorTicket,
  deleteOperatorTicket,
  getOperatorTicket,
  listCategories,
  listDepartments,
  listOperatorTickets,
} from "@/lib/ticketsApi";
import type { Ticket, TicketStatus } from "@/types/domain";

const PAGE_SIZE = 6;

const statuses: Array<{ value: TicketStatus | ""; label: string }> = [
  { value: "", label: "Усі" },
  { value: "in_progress", label: "В обробці" },
  { value: "answered", label: "З відповіддю" },
  { value: "closed", label: "Закриті" },
];

export default function OperatorPage() {
  return (
    <AuthGuard roles={["operator", "admin"]}>
      <AppShell>
        <OperatorWorkspace />
      </AppShell>
    </AuthGuard>
  );
}

function OperatorWorkspace() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">("");
  const [assignedToMe, setAssignedToMe] = useState<"" | "true" | "false">("");
  const [categoryId, setCategoryId] = useState("");
  const [sortBy, setSortBy] = useState<"created_desc" | "category">("created_desc");
  const [offset, setOffset] = useState(0);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const profileComplete = isProfileComplete(user);
  const issues = profileIssues(user);

  const ticketsQuery = useQuery({
    queryKey: ["operatorTickets", statusFilter, assignedToMe, categoryId, sortBy, offset],
    queryFn: () => listOperatorTickets({
      statusFilter,
      assignedToMe,
      categoryId,
      sortBy,
      limit: PAGE_SIZE,
      offset,
    }),
    enabled: profileComplete,
  });

  const catalogQuery = useQuery({
    queryKey: ["catalog"],
    queryFn: async () => {
      const [categories, departments] = await Promise.all([listCategories(), listDepartments()]);
      return { categories, departments };
    },
    enabled: profileComplete,
  });

  const claimMutation = useMutation({
    mutationFn: claimOperatorTicket,
    onSuccess: async (ticket) => {
      setSelectedTicket(ticket);
      await queryClient.invalidateQueries({ queryKey: ["operatorTickets"] });
    },
    onError: (err) => {
      setActionError(err instanceof Error ? err.message : "Не вдалося взяти заявку в роботу.");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteOperatorTicket,
    onSuccess: async () => {
      setSelectedTicket(null);
      await queryClient.invalidateQueries({ queryKey: ["operatorTickets"] });
    },
    onError: (err) => {
      setActionError(err instanceof Error ? err.message : "Не вдалося видалити заявку.");
    },
  });

  useEffect(() => {
    setOffset(0);
    setSelectedTicket(null);
  }, [statusFilter, assignedToMe, categoryId, sortBy]);

  const ticketsPage = ticketsQuery.data;
  const tickets = ticketsPage?.items ?? [];
  const total = ticketsPage?.total ?? 0;
  const limit = ticketsPage?.limit ?? PAGE_SIZE;
  const currentPage = Math.floor(offset / limit) + 1;
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + limit, total);

  useEffect(() => {
    if (!ticketsPage || total === 0 || offset < total) return;
    setOffset(Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE);
  }, [offset, ticketsPage, total]);

  async function refreshQueue() {
    await ticketsQuery.refetch();
  }

  async function refreshAfterTicketChange(ticket: Ticket) {
    setSelectedTicket(ticket);
    await queryClient.invalidateQueries({ queryKey: ["operatorTickets"] });
  }

  async function openTicket(ticketId: string) {
    setDetailLoading(true);
    setActionError(null);
    try {
      const ticket = await getOperatorTicket(ticketId);
      setSelectedTicket(ticket);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не вдалося завантажити заявку.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function claimTicket(ticketId: string) {
    setActionError(null);
    await claimMutation.mutateAsync(ticketId);
  }

  async function deleteTicket(ticketId: string) {
    if (!window.confirm("Видалити цю заявку?")) return;
    setActionError(null);
    await deleteMutation.mutateAsync(ticketId);
  }

  function changeStatusFilter(value: TicketStatus | "") {
    setStatusFilter(value);
  }

  function changeAssignedFilter(value: "" | "true" | "false") {
    setAssignedToMe(value);
  }

  function changeCategoryFilter(value: string) {
    setCategoryId(value);
  }

  function changeSort(value: "created_desc" | "category") {
    setSortBy(value);
  }

  function changePage(page: number) {
    setOffset((page - 1) * PAGE_SIZE);
  }

  return (
    <>
      <div className="section-title">
        <div>
          <h1>Операторська черга</h1>
          <p className="muted">
            Класифіковані заявки, аудіо, текст і блокування заявки за оператором.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={ticketsQuery.isFetching}
          onClick={refreshQueue}
          type="button"
        >
          <RefreshCw className={ticketsQuery.isFetching ? "spin" : undefined} size={18} />
          Оновити
        </button>
      </div>

      {actionError && <ErrorState message={actionError} />}

      {!profileComplete ? (
        <ProfileRequired issues={issues} />
      ) : (
        <>
          <div className="toolbar filters-toolbar">
            <select
              className="search-input"
              onChange={(event) => changeStatusFilter(event.target.value as TicketStatus | "")}
              value={statusFilter}
            >
              {statuses.map((item) => (
                <option key={item.value || "all"} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <select
              className="search-input"
              onChange={(event) => changeAssignedFilter(event.target.value as "" | "true" | "false")}
              value={assignedToMe}
            >
              <option value="">Усі призначення</option>
              <option value="true">Мої заявки</option>
              <option value="false">Вільні заявки</option>
            </select>
            <select
              className="search-input"
              disabled={catalogQuery.isLoading}
              onChange={(event) => changeCategoryFilter(event.target.value)}
              value={categoryId}
            >
              <option value="">Усі категорії</option>
              {catalogQuery.data?.categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
            <select
              className="search-input"
              onChange={(event) => changeSort(event.target.value as "created_desc" | "category")}
              value={sortBy}
            >
              <option value="created_desc">За датою створення</option>
              <option value="category">За категорією</option>
            </select>
          </div>

          <div className="grid-two">
            <section className="panel">
              <div className="panel-header">
                <h2>Заявки</h2>
                {total > 0 && (
                  <span className="muted small">
                    {pageStart}-{pageEnd} з {total}
                  </span>
                )}
              </div>

              {ticketsQuery.isLoading ? (
                <LoadingState message="Завантажуємо чергу..." />
              ) : ticketsQuery.isError ? (
                <ErrorState message="Не вдалося завантажити чергу." onRetry={refreshQueue} />
              ) : (
                <>
                  <div className="ticket-list">
                    {tickets.length === 0 && (
                      <EmptyState message="Заявок за цими фільтрами немає." />
                    )}
                    {tickets.map((ticket) => (
                      <button
                        className={selectedTicket?.id === ticket.id ? "ticket-row active" : "ticket-row"}
                        disabled={detailLoading}
                        key={ticket.id}
                        onClick={() => openTicket(ticket.id)}
                        type="button"
                      >
                        <div className="ticket-row-top">
                          <span className="ticket-title">
                            {ticket.title ?? ticket.edited_text ?? ticket.id}
                          </span>
                        </div>
                        <div className="toolbar">
                          <PriorityBadge priority={ticket.priority} />
                          <span className="muted small">{requesterSummary(ticket.author)}</span>
                          <span className="muted small">
                            {new Date(ticket.created_at).toLocaleString("uk-UA")}
                          </span>
                          <span className="muted small">
                            {ticket.category?.name ?? "Без категорії"}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>

                  <Pagination
                    currentPage={currentPage}
                    disabled={ticketsQuery.isFetching}
                    onPageChange={changePage}
                    pageSize={PAGE_SIZE}
                    total={total}
                  />
                </>
              )}
            </section>

            {catalogQuery.isLoading ? (
              <LoadingState message="Завантажуємо каталог..." />
            ) : catalogQuery.isError ? (
              <ErrorState message="Не вдалося завантажити каталог." onRetry={() => void catalogQuery.refetch()} />
            ) : (
              <OperatorTicketDetail
                categories={catalogQuery.data?.categories ?? []}
                departments={catalogQuery.data?.departments ?? []}
                onClaim={claimTicket}
                onDelete={deleteTicket}
                onRefresh={refreshAfterTicketChange}
                ticket={selectedTicket}
              />
            )}
          </div>
        </>
      )}
    </>
  );
}
