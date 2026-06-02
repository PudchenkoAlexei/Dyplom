"use client";

import { Mic, MicOff, Phone, PhoneCall, PhoneOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { SimpleUser, type SimpleUserDelegate, type SimpleUserOptions } from "sip.js/lib/platform/web";

const browserHost = typeof window === "undefined" ? "127.0.0.1" : window.location.hostname;
const PBX_WS_URL = process.env.NEXT_PUBLIC_PBX_WS_URL ?? `ws://${browserHost}:8088/ws`;
const PBX_SIP_DOMAIN = process.env.NEXT_PUBLIC_PBX_SIP_DOMAIN ?? browserHost;
const PBX_WEBRTC_EXTENSION = process.env.NEXT_PUBLIC_PBX_WEBRTC_EXTENSION ?? "7002";
const PBX_WEBRTC_PASSWORD = process.env.NEXT_PUBLIC_PBX_WEBRTC_PASSWORD ?? "KpiWebPhone7002!";
const PBX_ASSISTANT_NUMBER = process.env.NEXT_PUBLIC_PBX_ASSISTANT_NUMBER ?? "7000";

type CallState = "idle" | "connecting" | "registered" | "calling" | "answered" | "ending";

const stateLabel: Record<CallState, string> = {
  idle: "Готово до дзвінка",
  connecting: "Підключення до PBX",
  registered: "Лінія підключена",
  calling: "Виклик довідкової",
  answered: "Розмова активна",
  ending: "Завершення дзвінка",
};

const stateHint: Partial<Record<CallState, string>> = {
  calling: "Дозвольте доступ до мікрофона, якщо браузер запитає.",
  answered: "Після сигналу ставте питання. Після відповіді пролунає новий сигнал для наступного питання.",
};

function formatDuration(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function callErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return "Доступ до мікрофона заборонено. Дозвольте мікрофон у браузері й спробуйте подзвонити ще раз.";
    }
    if (error.name === "NotFoundError" || error.name === "DevicesNotFoundError") {
      return "Мікрофон не знайдено. Підключіть мікрофон і спробуйте подзвонити ще раз.";
    }
    if (error.name === "NotReadableError") {
      return "Мікрофон зайнятий іншою програмою. Закрийте її або звільніть мікрофон і спробуйте ще раз.";
    }
  }
  if (error instanceof Error && error.message) {
    if (error.message.toLowerCase().includes("permission denied")) {
      return "Доступ до мікрофона заборонено. Дозвольте мікрофон у браузері й спробуйте подзвонити ще раз.";
    }
    return `Не вдалося виконати дзвінок: ${error.message}`;
  }
  return "Не вдалося виконати дзвінок.";
}

export function PbxCallButton() {
  const [callState, setCallState] = useState<CallState>("idle");
  const [callStartedAt, setCallStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [microphoneMuted, setMicrophoneMuted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const simpleUserRef = useRef<SimpleUser | null>(null);

  useEffect(() => {
    if (!callStartedAt) {
      setElapsedSeconds(0);
      return;
    }

    const startedAt = callStartedAt;

    function updateElapsed() {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    }

    updateElapsed();
    const interval = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(interval);
  }, [callStartedAt]);

  function resetCallState() {
    setCallState("idle");
    setCallStartedAt(null);
    setMicrophoneMuted(false);
  }

  function setMicrophoneEnabled(enabled: boolean) {
    simpleUserRef.current?.localMediaStream
      ?.getAudioTracks()
      .forEach((track) => {
        track.enabled = enabled;
      });
  }

  async function cleanup() {
    const simpleUser = simpleUserRef.current;
    simpleUserRef.current = null;
    if (!simpleUser) return;

    try {
      if (simpleUser.isConnected()) {
        await simpleUser.disconnect();
      }
    } catch {
      // Nothing useful for the user here.
    }
  }

  async function startCall() {
    if (callState !== "idle") return;
    if (!audioRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Браузер не підтримує дзвінок з мікрофона.");
      return;
    }

    setError(null);
    setMicrophoneMuted(false);
    setCallStartedAt(Date.now());
    setCallState("connecting");

    const delegate: SimpleUserDelegate = {
      onServerConnect: () => setCallState("registered"),
      onCallCreated: () => setCallState("calling"),
      onCallAnswered: () => setCallState("answered"),
      onCallHangup: () => {
        resetCallState();
        void cleanup();
      },
      onServerDisconnect: () => {
        resetCallState();
      },
    };

    const options: SimpleUserOptions = {
      aor: `sip:${PBX_WEBRTC_EXTENSION}@${PBX_SIP_DOMAIN}`,
      delegate,
      media: {
        constraints: { audio: true, video: false },
        remote: { audio: audioRef.current },
      },
      userAgentOptions: {
        authorizationUsername: PBX_WEBRTC_EXTENSION,
        authorizationPassword: PBX_WEBRTC_PASSWORD,
        contactName: PBX_WEBRTC_EXTENSION,
        displayName: "KPI Helpdesk Web",
      },
    };

    const simpleUser = new SimpleUser(PBX_WS_URL, options);
    simpleUserRef.current = simpleUser;

    try {
      await simpleUser.connect();
      setCallState("calling");
      await simpleUser.call(`sip:${PBX_ASSISTANT_NUMBER}@${PBX_SIP_DOMAIN}`);
    } catch (err) {
      setError(callErrorMessage(err));
      resetCallState();
      await cleanup();
    }
  }

  async function hangup() {
    if (callState === "idle") return;
    setCallState("ending");
    try {
      await simpleUserRef.current?.hangup();
    } catch {
      // Asterisk may already have ended the call after playing the answer.
    } finally {
      await cleanup();
      resetCallState();
    }
  }

  function toggleMicrophone() {
    const simpleUser = simpleUserRef.current;
    if (!simpleUser || callState !== "answered") return;

    const nextMuted = !microphoneMuted;
    if (nextMuted) {
      simpleUser.mute();
    } else {
      simpleUser.unmute();
    }
    setMicrophoneEnabled(!nextMuted);
    setMicrophoneMuted(nextMuted);
  }

  const inCall = callState !== "idle";
  const activeHint =
    microphoneMuted
      ? "Мікрофон вимкнено. Увімкніть його перед тим, як ставити питання."
      : (stateHint[callState] ??
        "Залишайтеся на лінії. Після відповіді система сама запросить наступне питання.");
  const canToggleMicrophone = callState === "answered";

  return (
    <div className="pbx-call-box">
      <div className="pbx-call-status">
        <strong>Телефонна довідкова</strong>
        <span>{stateLabel[callState]}</span>
        {stateHint[callState] && <small>{stateHint[callState]}</small>}
      </div>
      <div className="toolbar">
        {!inCall ? (
          <button className="primary-button" onClick={startCall} type="button">
            <Phone size={18} />
            Подзвонити з додатку
          </button>
        ) : (
          <button className="danger-button" onClick={hangup} type="button">
            <PhoneOff size={18} />
            Завершити дзвінок
          </button>
        )}
      </div>
      {error && <div className="error-box">{error}</div>}
      {inCall && (
        <div className="pbx-call-screen-backdrop" role="dialog" aria-modal="true" aria-label="Екран дзвінка">
          <div className="pbx-call-screen">
            <div className="pbx-call-screen-top">
              <span className="pbx-call-live">
                <span />
                Лінія активна
              </span>
              <span className="pbx-call-timer">{formatDuration(elapsedSeconds)}</span>
            </div>

            <div className="pbx-call-avatar" aria-hidden="true">
              <span className="pbx-call-pulse" />
              <PhoneCall size={44} />
            </div>

            <div className="pbx-call-screen-copy">
              <span className="muted small">Голосова довідкова</span>
              <h2>Довідка КПІ</h2>
              <p>{stateLabel[callState]}</p>
              <small>{activeHint}</small>
            </div>

            <div className="pbx-call-controls">
              <button
                aria-pressed={microphoneMuted}
                className={`pbx-call-mute-button${microphoneMuted ? " muted" : ""}`}
                disabled={!canToggleMicrophone}
                onClick={toggleMicrophone}
                type="button"
              >
                {microphoneMuted ? <MicOff size={22} /> : <Mic size={22} />}
                {microphoneMuted ? "Увімкнути" : "Вимкнути"}
              </button>
              <button className="pbx-call-hangup-button" onClick={hangup} type="button">
                <PhoneOff size={24} />
                Завершити
              </button>
            </div>
          </div>
        </div>
      )}
      <audio autoPlay ref={audioRef} />
    </div>
  );
}
