"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Send } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { AudioRecorder } from "@/components/AudioRecorder";
import { AuthGuard } from "@/components/AuthGuard";
import { EmptyState, ErrorState, LoadingState } from "@/components/FeedbackState";
import { ProfileRequired } from "@/components/ProfileRequired";
import { RequesterTicketDetail } from "@/components/RequesterTicketDetail";
import { PriorityBadge, StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { isProfileComplete, profileIssues } from "@/lib/profile";
import {
  createDraftFromAudio,
  createDraftFromBrowserTranscript,
  deleteRequesterTicket,
  getRequesterTicket,
  listMyTickets,
  submitTicket,
  type DraftTicketResponse,
} from "@/lib/ticketsApi";
import type { Ticket } from "@/types/domain";

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
  const queryClient = useQueryClient();
  const [selectedTicket, setSelectedTicket] = useState<Ticket | null>(null);
  const [recording, setRecording] = useState<{ blob: Blob; url: string; filename?: string } | null>(
    null,
  );
  const [liveTranscript, setLiveTranscript] = useState("");
  const [recorderVersion, setRecorderVersion] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const clientRequestIdRef = useRef(makeClientRequestId());
  const submitInFlightRef = useRef(false);

  const transcriptText = liveTranscript.trim();
  const canSubmitTicket = useMemo(
    () => Boolean(recording) || transcriptText.length >= 3,
    [recording, transcriptText.length],
  );
  const profileComplete = isProfileComplete(user);
  const issues = profileIssues(user);

  const ticketsQuery = useQuery({
    queryKey: ["myTickets"],
    queryFn: listMyTickets,
    enabled: profileComplete,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteRequesterTicket,
    onSuccess: async () => {
      setSelectedTicket(null);
      await queryClient.invalidateQueries({ queryKey: ["myTickets"] });
    },
    onError: (err) => {
      setActionError(err instanceof Error ? err.message : "Не вдалося видалити заявку.");
    },
  });

  const tickets = ticketsQuery.data ?? [];
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

  async function refreshTickets() {
    await ticketsQuery.refetch();
  }

  async function submitRecording() {
    if (submitInFlightRef.current || !canSubmitTicket) return;
    submitInFlightRef.current = true;
    setSubmitting(true);
    setActionError(null);
    try {
      const formData = new FormData();
      formData.append("client_request_id", clientRequestIdRef.current);
      if (recording) {
        formData.append("audio", recording.blob, recording.filename ?? "voice-ticket.webm");
      }

      let draftResponse: DraftTicketResponse;
      if (transcriptText.length >= 3) {
        formData.append("transcript_text", transcriptText);
        draftResponse = await createDraftFromBrowserTranscript(formData);
      } else if (recording) {
        draftResponse = await createDraftFromAudio(formData);
      } else {
        throw new Error("Додайте текст звернення або запишіть аудіо.");
      }

      const submitted = await submitTicket(draftResponse.ticket.id);

      setLiveTranscript("");
      setRecording(null);
      setSelectedTicket(submitted);
      setRecorderVersion((version) => version + 1);
      clientRequestIdRef.current = makeClientRequestId();
      await queryClient.invalidateQueries({ queryKey: ["myTickets"] });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не вдалося надіслати заявку.");
    } finally {
      submitInFlightRef.current = false;
      setSubmitting(false);
    }
  }

  async function openTicket(ticketId: string) {
    setDetailLoading(true);
    setActionError(null);
    try {
      const ticket = await getRequesterTicket(ticketId);
      setSelectedTicket(ticket);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не вдалося завантажити заявку.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function deleteTicket(ticketId: string) {
    if (!window.confirm("Видалити цю заявку?")) return;
    setActionError(null);
    await deleteMutation.mutateAsync(ticketId);
  }

  return (
    <>
      <div className="section-title">
        <div>
          <h1>Мої заявки</h1>
          <p className="muted">
            Запис голосового звернення, автоматична обробка та історія відповідей.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={ticketsQuery.isFetching}
          onClick={refreshTickets}
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
                disabled={submitting}
                onChange={(event) => setLiveTranscript(event.target.value)}
                placeholder="Під час запису тут з'являтиметься розпізнаний текст. Можна також просто написати звернення без аудіо."
                value={liveTranscript}
              />
            </label>
            {submitting && (
              <LoadingState message="Обробляємо звернення: розпізнавання тексту та класифікація моделлю..." />
            )}
            <div className="toolbar">
              {canSubmitTicket && (
                <button
                  className="primary-button"
                  disabled={submitting}
                  onClick={submitRecording}
                  type="button"
                >
                  <Send size={18} />
                  {submitting ? "Обробка..." : "Надіслати заявку"}
                </button>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <h2>Історія</h2>
            </div>
            {ticketsQuery.isLoading ? (
              <LoadingState message="Завантажуємо ваші заявки..." />
            ) : ticketsQuery.isError ? (
              <ErrorState message="Не вдалося завантажити заявки." onRetry={refreshTickets} />
            ) : (
              <div className="ticket-list">
                {tickets.length === 0 && <EmptyState message="Заявок поки немає." />}
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
                      <StatusBadge status={ticket.status} />
                    </div>
                    <div className="toolbar">
                      <PriorityBadge priority={ticket.priority} />
                      <span className="muted small">
                        {new Date(ticket.created_at).toLocaleString("uk-UA")}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      {profileComplete && (
        <RequesterTicketDetail
          busy={deleteMutation.isPending || detailLoading}
          currentUser={user}
          onDelete={deleteTicket}
          ticket={selectedTicket}
        />
      )}
    </>
  );
}
