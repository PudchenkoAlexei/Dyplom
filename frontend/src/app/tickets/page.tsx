"use client";

import { RefreshCw, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { AudioRecorder } from "@/components/AudioRecorder";
import { AuthGuard } from "@/components/AuthGuard";
import { ProfileRequired } from "@/components/ProfileRequired";
import { RequesterMeta } from "@/components/RequesterMeta";
import { PriorityBadge, StatusBadge } from "@/components/StatusBadge";
import { apiRequest, audioUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { isProfileComplete, profileIssues } from "@/lib/profile";
import type { Ticket } from "@/types/domain";

interface DraftTicketResponse {
  ticket: Ticket;
  transcript_text: string;
}

function makeClientRequestId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function TicketsPage() {
  return (
    <AuthGuard roles={["student", "teacher"]}>
      <AppShell>
        <RequesterWorkspace />
      </AppShell>
    </AuthGuard>
  );
}

function RequesterWorkspace() {
  const { user } = useAuth();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
  const [recording, setRecording] = useState<{ blob: Blob; url: string; filename?: string } | null>(
    null,
  );
  const [liveTranscript, setLiveTranscript] = useState("");
  const [recorderVersion, setRecorderVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const clientRequestIdRef = useRef(makeClientRequestId());
  const submitInFlightRef = useRef(false);

  const transcriptText = liveTranscript.trim();
  const canSubmitTicket = useMemo(
    () => Boolean(recording) || transcriptText.length >= 3,
    [recording, transcriptText.length],
  );
  const profileComplete = isProfileComplete(user);
  const issues = profileIssues(user);

  const loadTickets = useCallback(async () => {
    if (!profileComplete) {
      setTickets([]);
      setSelectedTicket(null);
      return;
    }
    const data = await apiRequest<Ticket[]>("/tickets/my");
    setTickets(data);
  }, [profileComplete]);

  useEffect(() => {
    void loadTickets();
  }, [loadTickets]);

  function handleRecordingReady(nextRecording: { blob: Blob; url: string; filename?: string }) {
    setRecording(nextRecording);
  }

  function handleRecordingStart() {
    setRecording(null);
    setLiveTranscript("");
    clientRequestIdRef.current = makeClientRequestId();
  }

  function handleRecordingReset() {
    setRecording(null);
    setLiveTranscript("");
    clientRequestIdRef.current = makeClientRequestId();
  }

  async function submitRecording() {
    if (submitInFlightRef.current || !canSubmitTicket) return;
    submitInFlightRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("client_request_id", clientRequestIdRef.current);
      if (recording) {
        formData.append("audio", recording.blob, recording.filename ?? "voice-ticket.webm");
      }

      let draftResponse: DraftTicketResponse;
      if (transcriptText.length >= 3) {
        formData.append("transcript_text", transcriptText);
        draftResponse = await apiRequest<DraftTicketResponse>("/tickets/draft-browser-transcript", {
          method: "POST",
          formData,
        });
      } else if (recording) {
        draftResponse = await apiRequest<DraftTicketResponse>("/tickets/draft-audio", {
          method: "POST",
          formData,
        });
      } else {
        throw new Error("Додайте текст звернення або запишіть аудіо.");
      }

      const submitted = await apiRequest<Ticket>(`/tickets/${draftResponse.ticket.id}/submit`, {
        method: "POST",
      });

      setLiveTranscript("");
      setRecording(null);
      setSelectedTicket(submitted);
      setRecorderVersion((version) => version + 1);
      clientRequestIdRef.current = makeClientRequestId();
      await loadTickets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося надіслати заявку.");
    } finally {
      submitInFlightRef.current = false;
      setBusy(false);
    }
  }

  async function openTicket(ticketId: string) {
    const ticket = await apiRequest<Ticket>(`/tickets/${ticketId}`);
    setSelectedTicket(ticket);
  }

  async function deleteTicket(ticketId: string) {
    if (!window.confirm("Видалити цю заявку?")) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest<unknown>(`/tickets/${ticketId}`, { method: "DELETE" });
      setSelectedTicket(null);
      await loadTickets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося видалити заявку.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="section-title">
        <div>
          <h1>Мої заявки</h1>
          <p className="muted">Запис голосового звернення, автоматична обробка та історія відповідей.</p>
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
        <div className="grid-two">
        <section className="panel">
          <div className="panel-header">
            <h2>Нове звернення</h2>
          </div>
          <AudioRecorder
            key={recorderVersion}
            onReady={handleRecordingReady}
            onReset={handleRecordingReset}
            onStart={handleRecordingStart}
            onTranscriptChange={setLiveTranscript}
          />
          <label className="field">
            <span>Текст звернення</span>
            <textarea
              onChange={(event) => setLiveTranscript(event.target.value)}
              placeholder="Під час запису тут з'являтиметься розпізнаний текст. Можна також просто написати звернення без аудіо."
              value={liveTranscript}
            />
          </label>
          <div className="toolbar">
            {canSubmitTicket && (
              <button className="primary-button" disabled={busy} onClick={submitRecording} type="button">
                <Send size={18} />
                {busy ? "Надсилання..." : "Надіслати заявку"}
              </button>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>Історія</h2>
          </div>
          <div className="ticket-list">
            {tickets.length === 0 && <div className="empty-state">Заявок поки немає.</div>}
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
                  <span className="muted small">{new Date(ticket.created_at).toLocaleString("uk-UA")}</span>
                </div>
              </button>
            ))}
          </div>
        </section>
        </div>
      )}

      {profileComplete && (
        <TicketDetail busy={busy} currentUser={user} onDelete={deleteTicket} ticket={selectedTicket} />
      )}
    </>
  );
}

function TicketDetail({
  ticket,
  busy,
  currentUser,
  onDelete,
}: {
  ticket: Ticket | null;
  busy: boolean;
  currentUser: Ticket["author"] | null;
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
          <audio className="audio-player" controls crossOrigin="use-credentials" src={audioUrl(ticket.id)} />
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
