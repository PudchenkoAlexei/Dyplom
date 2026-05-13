"use client";

import { Mic, Pause, RotateCcw, Square, Upload } from "lucide-react";
import { ChangeEvent, useEffect, useRef, useState } from "react";

interface ReadyRecording {
  blob: Blob;
  url: string;
  filename?: string;
}

interface BrowserSpeechRecognitionAlternative {
  transcript: string;
}

interface BrowserSpeechRecognitionResult {
  isFinal: boolean;
  0?: BrowserSpeechRecognitionAlternative;
}

interface BrowserSpeechRecognitionResultList {
  length: number;
  [index: number]: BrowserSpeechRecognitionResult;
}

interface BrowserSpeechRecognitionEvent extends Event {
  resultIndex: number;
  results: BrowserSpeechRecognitionResultList;
}

interface BrowserSpeechRecognitionErrorEvent extends Event {
  error: string;
}

interface BrowserSpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onend: (() => void) | null;
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null;
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null;
  abort: () => void;
  start: () => void;
  stop: () => void;
}

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

interface SpeechRecognitionWindow extends Window {
  SpeechRecognition?: BrowserSpeechRecognitionConstructor;
  webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
}

function microphoneErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return "Доступ до мікрофона заборонено. Дозвольте доступ у браузері або завантажте аудіофайл.";
    }
    if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
      return "Мікрофон не знайдено. Підключіть мікрофон або завантажте аудіофайл.";
    }
    if (error.name === "NotReadableError") {
      return "Мікрофон зайнятий іншою програмою. Закрийте її або завантажте аудіофайл.";
    }
  }
  return "Не вдалося почати запис. Перевірте доступ до мікрофона або завантажте аудіофайл.";
}

function recorderOptions(): MediaRecorderOptions | undefined {
  if (MediaRecorder.isTypeSupported("audio/webm")) {
    return { mimeType: "audio/webm" };
  }
  return undefined;
}

export function AudioRecorder({
  onReady,
  onReset,
  onStart,
  onTranscriptChange,
}: {
  onReady: (recording: ReadyRecording) => void;
  onReset?: () => void;
  onStart?: () => void;
  onTranscriptChange?: (text: string) => void;
}) {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const speechRecognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const [state, setState] = useState<"idle" | "recording" | "paused">("idle");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      speechRecognitionRef.current?.abort();
      speechRecognitionRef.current = null;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, [audioUrl]);

  function updateLiveTranscript(text: string) {
    onTranscriptChange?.(text);
  }

  function createSpeechRecognition(): BrowserSpeechRecognition | null {
    const speechWindow = window as SpeechRecognitionWindow;
    const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (!Recognition) {
      return null;
    }

    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "uk-UA";
    recognition.onresult = (event) => {
      let finalText = "";
      let interimText = "";

      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal || index < event.resultIndex) {
          finalText += `${text} `;
        } else {
          interimText += text;
        }
      }

      updateLiveTranscript(`${finalText}${interimText}`.trim());
    };
    recognition.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setError(
          "Браузер не дозволив живе розпізнавання мовлення. Аудіозапис можна завантажити на серверне розпізнавання.",
        );
      }
    };
    recognition.onend = () => {
      speechRecognitionRef.current = null;
    };
    return recognition;
  }

  function startLiveTranscript() {
    const recognition = createSpeechRecognition();
    if (!recognition) return;
    try {
      recognition.start();
      speechRecognitionRef.current = recognition;
    } catch {
      speechRecognitionRef.current = null;
    }
  }

  function stopLiveTranscript() {
    speechRecognitionRef.current?.stop();
    speechRecognitionRef.current = null;
  }

  async function startRecording() {
    setError(null);
    onStart?.();
    updateLiveTranscript("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Цей браузер не підтримує запис з мікрофона. Завантажте аудіофайл.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream, recorderOptions());
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setError("Під час запису сталася помилка. Спробуйте ще раз або завантажте аудіофайл.");
        stopLiveTranscript();
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        setState("idle");
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const url = URL.createObjectURL(blob);
        setAudioUrl(url);
        onReady({ blob, url, filename: "voice-ticket.webm" });
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      };
      recorder.start();
      startLiveTranscript();
      setState("recording");
    } catch (recordingError) {
      setError(microphoneErrorMessage(recordingError));
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      setState("idle");
    }
  }

  function pauseRecording() {
    if (!recorderRef.current) return;
    if (state === "recording") {
      recorderRef.current.pause();
      stopLiveTranscript();
      setState("paused");
    } else if (state === "paused") {
      recorderRef.current.resume();
      startLiveTranscript();
      setState("recording");
    }
  }

  function stopRecording() {
    stopLiveTranscript();
    recorderRef.current?.stop();
    setState("idle");
  }

  function resetRecording() {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    speechRecognitionRef.current?.abort();
    speechRecognitionRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setAudioUrl(null);
    updateLiveTranscript("");
    setError(null);
    recorderRef.current = null;
    chunksRef.current = [];
    onReset?.();
  }

  function handleAudioFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError(null);
    if (!file.type.startsWith("audio/")) {
      setError("Оберіть аудіофайл у форматі WebM, WAV, MP3, M4A або OGG.");
      event.target.value = "";
      return;
    }
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    const url = URL.createObjectURL(file);
    setAudioUrl(url);
    onReady({ blob: file, url, filename: file.name });
    event.target.value = "";
  }

  return (
    <div className="recorder-panel">
      <div className="toolbar">
        {state === "idle" ? (
          <button className="primary-button" onClick={startRecording} type="button">
            <Mic size={18} />
            Записати звернення
          </button>
        ) : (
          <>
            <button className="secondary-button" onClick={pauseRecording} type="button">
              <Pause size={18} />
              {state === "paused" ? "Продовжити" : "Пауза"}
            </button>
            <button className="danger-button" onClick={stopRecording} type="button">
              <Square size={18} />
              Завершити
            </button>
          </>
        )}
        <label className="secondary-button file-button">
          <Upload size={18} />
          Завантажити аудіо
          <input
            accept="audio/webm,audio/wav,audio/x-wav,audio/mpeg,audio/mp4,audio/ogg,.webm,.wav,.mp3,.m4a,.ogg"
            onChange={handleAudioFile}
            type="file"
          />
        </label>
        {audioUrl && (
          <button className="icon-button" onClick={resetRecording} title="Очистити запис" type="button">
            <RotateCcw size={18} />
          </button>
        )}
      </div>
      {error && <div className="error-box">{error}</div>}
      {audioUrl && <audio className="audio-player" controls src={audioUrl} />}
    </div>
  );
}
