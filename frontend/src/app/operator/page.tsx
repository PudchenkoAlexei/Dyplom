"use client";

import { Check, LockKeyhole, RefreshCw, Send, Trash2, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { ProfileRequired } from "@/components/ProfileRequired";
import { RequesterMeta, requesterSummary } from "@/components/RequesterMeta";
import { PriorityBadge, StatusBadge } from "@/components/StatusBadge";
import { apiRequest, audioUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { priorityLabel } from "@/lib/labels";
import { isProfileComplete, profileIssues } from "@/lib/profile";
import type { Category, Department, Priority, Ticket, TicketStatus } from "@/types/domain";

const statuses: Array<{ value: TicketStatus | ""; label: string }> = [
  { value: "", label: "Усі" },
  { value: "submitted", label: "Надіслані" },
  { value: "classified", label: "Нові" },
  { value: "in_progress", label: "В обробці" },
  { value: "answered", label: "З відповіддю" },
  { value: "closed", label: "Закриті" },
];

const priorities: Priority[] = ["low", "medium", "high"];

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
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">("");
  const [assignedToMe, setAssignedToMe] = useState<"" | "true" | "false">("");
  const [error, setError] = useState<string | null>(null);
  const profileComplete = isProfileComplete(user);
  const issues = profileIssues(user);

  const loadTickets = useCallback(async () => {
    if (!profileComplete) {
      setTickets([]);
      setSelectedTicket(null);
      return;
    }
    const params = new URLSearchParams();
    if (statusFilter) params.set("status_filter", statusFilter);
    if (assignedToMe) params.set("assigned_to_me", assignedToMe);
    const suffix = params.toString() ? `?${params}` : "";
    const data = await apiRequest<Ticket[]>(`/operator/tickets${suffix}`);
    setTickets(data);
  }, [assignedToMe, profileComplete, statusFilter]);

  async function loadCatalog() {
    const [categoryData, departmentData] = await Promise.all([
      apiRequest<Category[]>("/categories"),
      apiRequest<Department[]>("/departments"),
    ]);
    setCategories(categoryData);
    setDepartments(departmentData);
  }

  useEffect(() => {
    if (!profileComplete) return;
    void loadCatalog();
  }, [profileComplete]);

  useEffect(() => {
    void loadTickets();
  }, [loadTickets]);

  async function openTicket(ticketId: string) {
    const ticket = await apiRequest<Ticket>(`/operator/tickets/${ticketId}`);
    setSelectedTicket(ticket);
  }

  async function claimTicket(ticketId: string) {
    setError(null);
    try {
      const ticket = await apiRequest<Ticket>(`/operator/tickets/${ticketId}/claim`, { method: "POST" });
      setSelectedTicket(ticket);
      await loadTickets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося взяти заявку в роботу.");
    }
  }

  async function deleteTicket(ticketId: string) {
    if (!window.confirm("Видалити цю заявку?")) return;
    setError(null);
    try {
      await apiRequest<unknown>(`/operator/tickets/${ticketId}`, { method: "DELETE" });
      setSelectedTicket(null);
      await loadTickets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося видалити заявку.");
    }
  }

  return (
    <>
      <div className="section-title">
        <div>
          <h1>Операторська черга</h1>
          <p className="muted">Класифіковані заявки, аудіо, текст і блокування заявки за оператором.</p>
        </div>
        <button className="secondary-button" onClick={loadTickets} type="button">
          <RefreshCw size={18} />
          Оновити
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {!profileComplete ? (
        <ProfileRequired issues={issues} />
      ) : (
        <>
          <div className="toolbar filters-toolbar">
        <select
          className="search-input"
          onChange={(event) => setStatusFilter(event.target.value as TicketStatus | "")}
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
          onChange={(event) => setAssignedToMe(event.target.value as "" | "true" | "false")}
          value={assignedToMe}
        >
          <option value="">Усі призначення</option>
          <option value="true">Мої заявки</option>
          <option value="false">Вільні заявки</option>
        </select>
          </div>

          <div className="grid-two">
        <section className="panel">
          <div className="panel-header">
            <h2>Заявки</h2>
          </div>
          <div className="ticket-list">
            {tickets.length === 0 && <div className="empty-state">Заявок за цими фільтрами немає.</div>}
            {tickets.map((ticket) => (
              <button
                className={selectedTicket?.id === ticket.id ? "ticket-row active" : "ticket-row"}
                key={ticket.id}
                onClick={() => openTicket(ticket.id)}
                type="button"
              >
                <div className="ticket-row-top">
                  <span className="ticket-title">{ticket.title ?? ticket.edited_text ?? ticket.id}</span>
                  <StatusBadge status={ticket.status} />
                </div>
                <div className="toolbar">
                  <PriorityBadge priority={ticket.priority} />
                  <span className="muted small">{requesterSummary(ticket.author)}</span>
                  <span className="muted small">{ticket.category?.name ?? "Без категорії"}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <OperatorTicketDetail
          categories={categories}
          departments={departments}
          onClaim={claimTicket}
          onDelete={deleteTicket}
          onRefresh={async (ticket) => {
            setSelectedTicket(ticket);
            await loadTickets();
          }}
          ticket={selectedTicket}
        />
          </div>
        </>
      )}
    </>
  );
}

function OperatorTicketDetail({
  ticket,
  categories,
  departments,
  onClaim,
  onDelete,
  onRefresh,
}: {
  ticket: Ticket | null;
  categories: Category[];
  departments: Department[];
  onClaim: (ticketId: string) => Promise<void>;
  onDelete: (ticketId: string) => Promise<void>;
  onRefresh: (ticket: Ticket) => Promise<void>;
}) {
  const { user } = useAuth();
  const [categoryId, setCategoryId] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [priority, setPriority] = useState<Priority>("medium");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!ticket) return;
    setCategoryId(ticket.category?.id ?? "");
    setDepartmentId(ticket.department?.id ?? "");
    setPriority(ticket.priority ?? "medium");
    setMessage("");
  }, [ticket]);

  if (!ticket) {
    return <section className="empty-state">Оберіть заявку з черги.</section>;
  }

  const isAssignedToCurrentUser = ticket.assigned_operator_id === user?.id;
  const isAdmin = user?.role === "admin";
  const isClosed = ticket.status === "closed";
  const assignedOperatorName = ticket.assigned_operator?.full_name ?? ticket.assigned_operator?.email;
  const canClaim =
    !ticket.assigned_operator_id && (ticket.status === "submitted" || ticket.status === "classified");
  const canEdit = !isClosed && (isAdmin || isAssignedToCurrentUser);

  async function updateClassification() {
    if (!ticket) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiRequest<Ticket>(`/operator/tickets/${ticket.id}/classification`, {
        method: "PATCH",
        body: {
          category_id: categoryId,
          department_id: departmentId,
          priority,
        },
      });
      await onRefresh(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося оновити класифікацію.");
    } finally {
      setBusy(false);
    }
  }

  async function sendMessage() {
    if (!ticket || !message.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiRequest<Ticket>(`/operator/tickets/${ticket.id}/messages`, {
        method: "POST",
        body: { message },
      });
      setMessage("");
      await onRefresh(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося надіслати відповідь.");
    } finally {
      setBusy(false);
    }
  }

  async function closeTicket() {
    if (!ticket) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiRequest<Ticket>(`/operator/tickets/${ticket.id}/close`, { method: "POST" });
      await onRefresh(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося закрити заявку.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Заявка #{ticket.id.slice(0, 8)}</h2>
        <StatusBadge status={ticket.status} />
      </div>
      {error && <div className="error-box">{error}</div>}

      <div className="toolbar">
        <button
          className="primary-button"
          disabled={!canClaim || busy}
          onClick={() => onClaim(ticket.id)}
          type="button"
        >
          <LockKeyhole size={18} />
          {ticket.assigned_operator_id
            ? isAssignedToCurrentUser
              ? "Уже у вашій роботі"
              : "Заявка в роботі"
            : "Взяти в роботу"}
        </button>
        <button className="danger-button" disabled={!canEdit || busy || isClosed} onClick={closeTicket} type="button">
          <XCircle size={18} />
          Закрити
        </button>
        <button className="danger-button" disabled={busy} onClick={() => onDelete(ticket.id)} type="button">
          <Trash2 size={18} />
          Видалити
        </button>
      </div>

      {ticket.assigned_operator_id && (
        <div className="info-box">
          Заявку обробляє: {isAssignedToCurrentUser ? "ви" : assignedOperatorName ?? "інший оператор"}.
        </div>
      )}
      {!ticket.assigned_operator_id && !isAdmin && !isClosed && (
        <div className="info-box">Щоб відповідати або змінювати класифікацію, спочатку візьміть заявку в роботу.</div>
      )}
      {!canEdit && ticket.assigned_operator_id && !isClosed && (
        <div className="info-box">Редагування недоступне, доки заявка в роботі іншого оператора.</div>
      )}

      {ticket.audio && (
        <div className="detail-grid">
          <strong>Аудіозапис</strong>
          <audio className="audio-player" controls crossOrigin="use-credentials" src={audioUrl(ticket.id)} />
        </div>
      )}

      <div className="detail-grid">
        <strong>Текст звернення</strong>
        <p>{ticket.edited_text}</p>
      </div>

      <div className="meta-grid">
        <RequesterMeta user={ticket.author} />
        <label className="field">
          <span>Категорія</span>
          <select disabled={!canEdit || busy} onChange={(event) => setCategoryId(event.target.value)} value={categoryId}>
            <option value="">Оберіть категорію</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Підрозділ</span>
          <select disabled={!canEdit || busy} onChange={(event) => setDepartmentId(event.target.value)} value={departmentId}>
            <option value="">Оберіть підрозділ</option>
            {departments.map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Пріоритет</span>
          <select disabled={!canEdit || busy} onChange={(event) => setPriority(event.target.value as Priority)} value={priority}>
            {priorities.map((item) => (
              <option key={item} value={item}>
                {priorityLabel[item]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <button
        className="secondary-button"
        disabled={!canEdit || !categoryId || !departmentId || busy}
        onClick={updateClassification}
        type="button"
      >
        <Check size={18} />
        Зберегти класифікацію
      </button>

      <label className="field">
        <span>Відповідь користувачу</span>
        <textarea disabled={!canEdit || busy || isClosed} onChange={(event) => setMessage(event.target.value)} value={message} />
      </label>
      <button className="primary-button" disabled={!canEdit || !message.trim() || busy || isClosed} onClick={sendMessage} type="button">
        <Send size={18} />
        Надіслати відповідь
      </button>
    </section>
  );
}
