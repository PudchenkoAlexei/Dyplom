import { Trash2 } from "lucide-react";

import { RequesterMeta } from "@/components/RequesterMeta";
import { PriorityBadge, StatusBadge } from "@/components/StatusBadge";
import { ticketAudioUrl } from "@/lib/ticketsApi";
import type { Ticket, User } from "@/types/domain";

export function RequesterTicketDetail({
  ticket,
  busy,
  currentUser,
  onDelete,
}: {
  ticket: Ticket | null;
  busy: boolean;
  currentUser: User | null;
  onDelete: (ticketId: string) => Promise<void>;
}) {
  if (!ticket) {
    return <section className="empty-state">Оберіть заявку для перегляду деталей.</section>;
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Заявка #{ticket.id.slice(0, 8)}</h2>
        <StatusBadge status={ticket.status} />
      </div>
      <div className="toolbar">
        <button className="danger-button" disabled={busy} onClick={() => onDelete(ticket.id)} type="button">
          <Trash2 size={18} />
          Видалити заявку
        </button>
      </div>
      <div className="meta-grid">
        <RequesterMeta user={ticket.author ?? currentUser} />
        <div className="meta-item">
          <span>Категорія</span>
          <strong>{ticket.category?.name ?? "Не визначено"}</strong>
        </div>
        <div className="meta-item">
          <span>Підрозділ</span>
          <strong>{ticket.department?.name ?? "Не визначено"}</strong>
        </div>
        <div className="meta-item">
          <span>Пріоритет</span>
          <PriorityBadge priority={ticket.priority} />
        </div>
      </div>

      {ticket.audio && (
        <div className="detail-grid">
          <strong>Аудіозапис</strong>
          <audio className="audio-player" controls crossOrigin="use-credentials" src={ticketAudioUrl(ticket.id)} />
        </div>
      )}

      <div className="detail-grid">
        <strong>Текст звернення</strong>
        <p>{ticket.edited_text}</p>
      </div>

      <div className="detail-grid">
        <strong>Відповіді</strong>
        <div className="message-list">
          {ticket.messages.length === 0 && <div className="empty-state">Відповідей поки немає.</div>}
          {ticket.messages.map((message) => (
            <div className="message-item" key={message.id}>
              <p>{message.message}</p>
              <span className="muted small">{new Date(message.created_at).toLocaleString("uk-UA")}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
