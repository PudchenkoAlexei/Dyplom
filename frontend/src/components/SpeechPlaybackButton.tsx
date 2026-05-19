"use client";

import { Square, Volume2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { synthesizeVoiceAssistantSpeech } from "@/lib/ticketsApi";

interface SpeechPlaybackButtonProps {
  text: string;
  label?: string;
  autoPlayKey?: string | number | null;
}

function getUkrainianVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  return (
    voices.find((voice) => voice.lang.toLowerCase() === "uk-ua") ??
    voices.find((voice) => voice.lang.toLowerCase().startsWith("uk")) ??
    null
  );
}

export function SpeechPlaybackButton({
  text,
  label = "Озвучити",
  autoPlayKey = null,
}: SpeechPlaybackButtonProps) {
  const [isSupported, setIsSupported] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isLoadingAudio, setIsLoadingAudio] = useState(false);
  const [voicesReady, setVoicesReady] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const speechText = useMemo(() => text.trim(), [text]);

  useEffect(() => {
    if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
      return;
    }

    setIsSupported(true);
    const markVoicesReady = () => setVoicesReady(true);
    window.speechSynthesis.addEventListener("voiceschanged", markVoicesReady);
    markVoicesReady();

    return () => {
      stopAudio();
      window.speechSynthesis.cancel();
      window.speechSynthesis.removeEventListener("voiceschanged", markVoicesReady);
    };
  }, []);

  useEffect(() => {
    if (!autoPlayKey || !speechText || !isSupported || !voicesReady) return;
    speak();
    // Auto-play is intentionally tied to the response key, not every state change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoPlayKey, isSupported, voicesReady]);

  function stopAudio() {
    audioRef.current?.pause();
    audioRef.current = null;
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
  }

  function stopSpeaking() {
    stopAudio();
    window.speechSynthesis.cancel();
    setIsSpeaking(false);
  }

  function speakWithBrowserVoice() {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(speechText);
    utterance.lang = "uk-UA";
    utterance.rate = 0.9;
    utterance.pitch = 1;
    utterance.voice = getUkrainianVoice();
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    setIsSpeaking(true);
    window.speechSynthesis.speak(utterance);
  }

  async function speak() {
    if (!speechText || !isSupported) return;
    if (isSpeaking) {
      stopSpeaking();
      return;
    }

    stopSpeaking();
    setIsLoadingAudio(true);
    try {
      const blob = await synthesizeVoiceAssistantSpeech(speechText);
      const url = URL.createObjectURL(blob);
      audioUrlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        stopAudio();
        setIsSpeaking(false);
      };
      audio.onerror = () => {
        stopAudio();
        setIsSpeaking(false);
        speakWithBrowserVoice();
      };
      setIsSpeaking(true);
      await audio.play();
    } catch {
      speakWithBrowserVoice();
    } finally {
      setIsLoadingAudio(false);
    }
  }

  if (!speechText || !isSupported) {
    return null;
  }

  return (
    <button
      className="secondary-button"
      disabled={isLoadingAudio || !voicesReady}
      onClick={speak}
      type="button"
    >
      {isSpeaking ? <Square size={18} /> : <Volume2 size={18} />}
      {isLoadingAudio ? "Готуємо голос..." : isSpeaking ? "Зупинити" : label}
    </button>
  );
}
