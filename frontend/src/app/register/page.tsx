"use client";

import { UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { UserRole } from "@/types/domain";

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRole>("student");
  const [studentGroup, setStudentGroup] = useState("");
  const [studentGroups, setStudentGroups] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    async function loadGroups() {
      try {
        setStudentGroups(await apiRequest<string[]>("/users/student-groups"));
      } catch {
        setStudentGroups([]);
      }
    }
    void loadGroups();
  }, []);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register({
        email,
        password,
        full_name: fullName,
        role,
        student_group: role === "student" ? studentGroup : null,
      });
      router.replace("/tickets");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося зареєструватися.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-aside">
        <h1>KPI Voice Helpdesk</h1>
        <p>
          Студент і викладач створюють звернення з аудіо, редагують транскрипт і
          відстежують відповіді операторів.
        </p>
      </section>
      <section className="auth-form-wrap">
        <form className="auth-form" onSubmit={handleSubmit}>
          <h2>Реєстрація</h2>
          {error && <div className="error-box">{error}</div>}
          <label className="field">
            <span>ПІБ</span>
            <input
              autoComplete="name"
              onChange={(event) => setFullName(event.target.value)}
              required
              value={fullName}
            />
          </label>
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
            <span>Роль</span>
            <select
              onChange={(event) => {
                setRole(event.target.value as UserRole);
                setStudentGroup("");
              }}
              value={role}
            >
              <option value="student">Студент</option>
              <option value="teacher">Викладач</option>
            </select>
          </label>
          {role === "student" && (
            <label className="field">
              <span>Група</span>
              <select
                onChange={(event) => setStudentGroup(event.target.value)}
                required
                value={studentGroup}
              >
                <option value="">Оберіть групу</option>
                {studentGroups.map((group) => (
                  <option key={group} value={group}>
                    {group}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            <span>Пароль</span>
            <input
              autoComplete="new-password"
              minLength={10}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <button className="primary-button" disabled={submitting} type="submit">
            <UserPlus size={18} />
            {submitting ? "Створення..." : "Створити акаунт"}
          </button>
          <p className="muted small">
            Вже є акаунт? <Link href="/login">Увійти</Link>
          </p>
        </form>
      </section>
    </main>
  );
}
