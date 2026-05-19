"use client";

import { Headphones, RotateCcw, TicketPlus } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { AudioRecorder } from "@/components/AudioRecorder";
import { AuthGuard } from "@/components/AuthGuard";
import { ErrorState, LoadingState } from "@/components/FeedbackState";
import { ProfileRequired } from "@/components/ProfileRequired";
import { SpeechPlaybackButton } from "@/components/SpeechPlaybackButton";
import { useAuth } from "@/lib/auth";
import { isProfileComplete, profileIssues } from "@/lib/profile";
import {
  askVoiceAssistant,
  createDraftFromBrowserTranscript,
  submitTicket,
  type VoiceAssistantResponse,
} from "@/lib/ticketsApi";

function makeClientRequestId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function AssistantPage() {
  return (
    <AuthGuard roles={["student", "teacher"]}>
      <AppShell>
        <VoiceAssistantWorkspace />
      </AppShell>
    </AuthGuard>
  );
}

function VoiceAssistantWorkspace() {
  const { user } = useAuth();
  const [recording, setRecording] = useState<{ blob: Blob; url: string; filename?: string } | null>(
    null,
  );
  const [questionText, setQuestionText] = useState("");
  const [response, setResponse] = useState<VoiceAssistantResponse | null>(null);
  const [recorderVersion, setRecorderVersion] = useState(0);
  const [responseVersion, setResponseVersion] = useState(0);
  const [asking, setAsking] = useState(false);
  const [creatingTicket, setCreatingTicket] = useState(false);
  const [createdTicketId, setCreatedTicketId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const askingRef = useRef(false);
  const autoAskAfterRecordingRef = useRef(false);
  const clientRequestIdRef = useRef(makeClientRequestId());
  const questionTextRef = useRef("");

  const profileComplete = isProfileComplete(user);
  const issues = profileIssues(user);
  const normalizedQuestion = questionText.trim();

  function updateQuestionText(text: string) {
    questionTextRef.current = text;
    setQuestionText(text);
  }

  function handleRecordingStart() {
    setRecording(null);
    updateQuestionText("");
    setResponse(null);
    setCreatedTicketId(null);
    setActionError(null);
    autoAskAfterRecordingRef.current = false;
  }

  function handleRecordingReset() {
    setRecording(null);
    updateQuestionText("");
    setResponse(null);
    setCreatedTicketId(null);
    setActionError(null);
    autoAskAfterRecordingRef.current = false;
  }

  function handleRecordingReady(nextRecording: { blob: Blob; url: string; filename?: string }) {
    setRecording(nextRecording);
    if (!autoAskAfterRecordingRef.current) return;

    autoAskAfterRecordingRef.current = false;
    void askAssistant(nextRecording, questionTextRef.current);
  }

  function handleRecordingAutoStop() {
    autoAskAfterRecordingRef.current = true;
  }

  async function askAssistant(
    nextRecording: { blob: Blob; url: string; filename?: string } | null = recording,
    nextQuestionText = questionTextRef.current,
  ) {
    const question = nextQuestionText.trim();
    if ((!nextRecording && question.length < 3) || askingRef.current) return;
    askingRef.current = true;
    setAsking(true);
    setActionError(null);
    setCreatedTicketId(null);
    try {
      const formData = new FormData();
      if (question.length >= 3) {
        formData.append("question_text", question);
      }
      if (nextRecording) {
        formData.append("audio", nextRecording.blob, nextRecording.filename ?? "voice-question.webm");
      }
      const answer = await askVoiceAssistant(formData);
      updateQuestionText(answer.question_text);
      setResponse(answer);
      setResponseVersion((version) => version + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не вдалося отримати голосову відповідь.");
    } finally {
      askingRef.current = false;
      setAsking(false);
    }
  }

  async function createTicketFromQuestion() {
    const ticketText = response?.question_text || normalizedQuestion;
    if (ticketText.trim().length < 3 || creatingTicket) return;
    setCreatingTicket(true);
    setActionError(null);
    try {
      const formData = new FormData();
      formData.append("client_request_id", clientRequestIdRef.current);
      formData.append("transcript_text", ticketText.trim());
      if (recording) {
        formData.append("audio", recording.blob, recording.filename ?? "voice-question.webm");
      }
      const draft = await createDraftFromBrowserTranscript(formData);
      const submitted = await submitTicket(draft.ticket.id);
      setCreatedTicketId(submitted.id);
      clientRequestIdRef.current = makeClientRequestId();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Не вдалося створити заявку.");
    } finally {
      setCreatingTicket(false);
    }
  }

  function resetConversation() {
    setRecording(null);
    updateQuestionText("");
    setResponse(null);
    setCreatedTicketId(null);
    setActionError(null);
    autoAskAfterRecordingRef.current = false;
    setRecorderVersion((version) => version + 1);
    clientRequestIdRef.current = makeClientRequestId();
  }

  return (
    <>
      <div className="section-title">
        <div>
          <h1>Голосова довідкова</h1>
          <p className="muted">Питання голосом, автоматична відповідь на основі FAQ КПІ.</p>
        </div>
        <button className="secondary-button" onClick={resetConversation} type="button">
          <RotateCcw size={18} />
          Новий дзвінок
        </button>
      </div>

      {actionError && <ErrorState message={actionError} />}

      {!profileComplete ? (
        <ProfileRequired issues={issues} />
      ) : (
        <div className="grid-two">
          <section className="panel assistant-call-panel">
            <div className="panel-header">
              <h2>Запит</h2>
              <span className="call-state">
                <Headphones size={18} />
                {asking ? "Обробка" : "Готово"}
              </span>
            </div>

            <AudioRecorder
              key={recorderVersion}
              autoStopAfterTranscriptSilenceMs={2000}
              clearTitle="Очистити питання"
              hideUpload
              onAutoStop={handleRecordingAutoStop}
              onReady={handleRecordingReady}
              onReset={handleRecordingReset}
              onStart={handleRecordingStart}
              onTranscriptChange={updateQuestionText}
              recordLabel="Почати розмову"
              recordingFilename="voice-question.webm"
            />

            <label className="field">
              <span>Розпізнане питання</span>
              <textarea
                disabled={asking || creatingTicket}
                onChange={(event) => updateQuestionText(event.target.value)}
                value={questionText}
              />
            </label>

            {asking && <LoadingState message="Довідкова служба формує відповідь..." />}
          </section>

          <section className="panel assistant-answer-panel">
            <div className="panel-header">
              <h2>Відповідь</h2>
              {response && (
                <span className="muted small">
                  {Math.round(response.confidence * 100)}% збіг
                </span>
              )}
            </div>

            {!response ? (
              <div className="empty-state">Відповідь з’явиться після запиту.</div>
            ) : (
              <>
                <div className="assistant-answer">
                  <p>{response.answer_text}</p>
                </div>
                <div className="toolbar">
                  <SpeechPlaybackButton
                    autoPlayKey={responseVersion}
                    label="Повторити голосом"
                    text={response.answer_text}
                  />
                  <button
                    className="secondary-button"
                    disabled={creatingTicket}
                    onClick={createTicketFromQuestion}
                    type="button"
                  >
                    <TicketPlus size={18} />
                    {creatingTicket ? "Створення..." : "Заявка оператору"}
                  </button>
                </div>

                {createdTicketId && (
                  <div className="info-box">
                    Заявку #{createdTicketId.slice(0, 8)} створено.{" "}
                    <Link href="/tickets">Перейти до моїх заявок</Link>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </>
  );
}
