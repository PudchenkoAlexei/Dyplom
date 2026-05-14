"use client";

import { Check, LockKeyhole, Send, Trash2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { AudioRecorder, type ReadyRecording } from "@/components/AudioRecorder";
import { RequesterMeta } from "@/components/RequesterMeta";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { priorityLabel } from "@/lib/labels";
import {
  addOperatorMessage,
  addOperatorVoiceMessage,
  closeOperatorTicket,
  ticketAudioUrl,
  updateOperatorClassification,
} from "@/lib/ticketsApi";
import type { Category, Department, Priority, Ticket } from "@/types/domain";

const priorities: Priority[] = ["low", "medium", "high"];

export function OperatorTicketDetail({
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
  const [voiceResponse, setVoiceResponse] = useState<ReadyRecording | null>(null);
  const [voiceTranscript, setVoiceTranscript] = useState("");
  const [voiceRecorderVersion, setVoiceRecorderVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!ticket) return;
    setCategoryId(ticket.category?.id ?? "");
    setDepartmentId(ticket.department?.id ?? "");
    setPriority(ticket.priority ?? "medium");
    setMessage("");
    setVoiceResponse(null);
    setVoiceTranscript("");
    setVoiceRecorderVersion((version) => version + 1);
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
      const updated = await updateOperatorClassification(ticket.id, {
        category_id: categoryId,
        department_id: departmentId,
        priority,
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
      const updated = await addOperatorMessage(ticket.id, message);
      setMessage("");
      await onRefresh(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося надіслати відповідь.");
    } finally {
      setBusy(false);
    }
  }

  async function sendVoiceMessage() {
    if (!ticket || !voiceResponse) return;
    setBusy(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("audio", voiceResponse.blob, voiceResponse.filename ?? "operator-response.webm");
      if (voiceTranscript.trim().length >= 3) {
        formData.append("transcript_text", voiceTranscript.trim());
      }
      const updated = await addOperatorVoiceMessage(ticket.id, formData);
      setVoiceResponse(null);
      setVoiceTranscript("");
      setVoiceRecorderVersion((version) => version + 1);
      await onRefresh(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося надіслати голосову відповідь.");
    } finally {
      setBusy(false);
    }
  }

  async function closeTicket() {
    if (!ticket) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await closeOperatorTicket(ticket.id);
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
          <audio className="audio-player" controls crossOrigin="use-credentials" src={ticketAudioUrl(ticket.id)} />
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

      {canEdit && !isClosed && (
        <div className="detail-grid">
          <strong>Голосова відповідь</strong>
          <AudioRecorder
            key={voiceRecorderVersion}
            clearTitle="Очистити аудіовідповідь"
            onReady={setVoiceResponse}
            onReset={() => {
              setVoiceResponse(null);
              setVoiceTranscript("");
            }}
            onTranscriptChange={setVoiceTranscript}
            recordLabel="Записати відповідь"
            recordingFilename="operator-response.webm"
            uploadLabel="Завантажити аудіовідповідь"
          />
          {voiceTranscript.trim().length >= 3 && (
            <div className="info-box">Попередній текст відповіді: {voiceTranscript}</div>
          )}
          <button
            className="primary-button"
            disabled={!voiceResponse || busy}
            onClick={sendVoiceMessage}
            type="button"
          >
            <Send size={18} />
            Надіслати голосом
          </button>
        </div>
      )}
    </section>
  );
}
