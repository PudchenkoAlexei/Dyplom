"use client";

import { LogIn } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const user = await login(email, password);
      router.replace(user.role === "operator" || user.role === "admin" ? "/operator" : "/tickets");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося увійти.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-aside">
        <h1>KPI Voice Helpdesk</h1>
        <p>Система приймає голосові звернення студентів і викладачів.</p>
      </section>
      <section className="auth-form-wrap">
        <form className="auth-form" onSubmit={handleSubmit}>
          <h2>Вхід</h2>
          {error && <div className="error-box">{error}</div>}
          <label className="field">
            <span>Email</span>
            <input
              autoComplete="email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <label className="field">
            <span>Пароль</span>
            <input
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <button className="primary-button" disabled={submitting} type="submit">
            <LogIn size={18} />
            {submitting ? "Вхід..." : "Увійти"}
          </button>
          <p className="muted small">
            Немає акаунта? <Link href="/register">Зареєструватися</Link>
          </p>
        </form>
      </section>
    </main>
  );
}
