"use client";

import { FileText, Trash2 } from "lucide-react";
import { useState } from "react";

import { RequesterMeta } from "@/components/RequesterMeta";
import { PriorityBadge, StatusBadge } from "@/components/StatusBadge";
import { ticketAudioUrl, ticketMessageAudioUrl, transcribeTicketMessage } from "@/lib/ticketsApi";
import type { Ticket, User } from "@/types/domain";

export function RequesterTicketDetail({
  ticket,
  busy,
  currentUser,
  onDelete,
  onRefresh,
}: {
  ticket: Ticket | null;
  busy: boolean;
  currentUser: User | null;
  onDelete: (ticketId: string) => Promise<void>;
  onRefresh: (ticket: Ticket) => Promise<void> | void;
}) {
  const [transcribingMessageId, setTranscribingMessageId] = useState<string | null>(null);
  const [transcriptionError, setTranscriptionError] = useState<string | null>(null);

  if (!ticket) {
    return <section className="empty-state">Оберіть заявку для перегляду деталей.</section>;
  }
  const activeTicket = ticket;

  async function handleTranscribeMessage(messageId: string) {
    setTranscribingMessageId(messageId);
    setTranscriptionError(null);
    try {
      const updated = await transcribeTicketMessage(activeTicket.id, messageId);
      await onRefresh(updated);
    } catch (err) {
      setTranscriptionError(
        err instanceof Error ? err.message : "Не вдалося перевести голосову відповідь у текст.",
      );
    } finally {
      setTranscribingMessageId(null);
    }
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Заявка #{activeTicket.id.slice(0, 8)}</h2>
        {activeTicket.status !== "classified" && <StatusBadge status={activeTicket.status} />}
      </div>
      <div className="toolbar">
        <button className="danger-button" disabled={busy} onClick={() => onDelete(activeTicket.id)} type="button">
          <Trash2 size={18} />
          Видалити заявку
        </button>
      </div>
      <div className="meta-grid">
        <RequesterMeta user={activeTicket.author ?? currentUser} />
        <div className="meta-item">
          <span>Категорія</span>
          <strong>{activeTicket.category?.name ?? "Не визначено"}</strong>
        </div>
        <div className="meta-item">
          <span>Підрозділ</span>
          <strong>{activeTicket.department?.name ?? "Не визначено"}</strong>
        </div>
        <div className="meta-item">
          <span>Пріоритет</span>
          <PriorityBadge priority={activeTicket.priority} />
        </div>
      </div>

      {activeTicket.audio && (
        <div className="detail-grid">
          <strong>Аудіозапис</strong>
          <audio className="audio-player" controls crossOrigin="use-credentials" src={ticketAudioUrl(activeTicket.id)} />
        </div>
      )}

      <div className="detail-grid">
        <strong>Текст звернення</strong>
        <p>{activeTicket.edited_text}</p>
      </div>

      <div className="detail-grid">
        <strong>Відповіді</strong>
        {transcriptionError && <div className="error-box">{transcriptionError}</div>}
        <div className="message-list">
          {activeTicket.messages.length === 0 && <div className="empty-state">Відповідей поки немає.</div>}
          {activeTicket.messages.map((message) => (
            <div className="message-item" key={message.id}>
              {message.message && <p>{message.message}</p>}
              {message.audio_mime_type && (
                <div className="message-audio-block">
                  <audio
                    className="audio-player"
                    controls
                    crossOrigin="use-credentials"
                    src={ticketMessageAudioUrl(activeTicket.id, message.id)}
                  />
                  {message.transcript_text ? (
                    <p className="message-transcript">
                      <strong>Текст голосової відповіді:</strong> {message.transcript_text}
                    </p>
                  ) : (
                    <button
                      className="secondary-button"
                      disabled={busy || transcribingMessageId === message.id}
                      onClick={() => handleTranscribeMessage(message.id)}
                      type="button"
                    >
                      <FileText size={18} />
                      {transcribingMessageId === message.id ? "Перетворюємо..." : "Перевести у текст"}
                    </button>
                  )}
                </div>
              )}
              <span className="muted small">{new Date(message.created_at).toLocaleString("uk-UA")}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
