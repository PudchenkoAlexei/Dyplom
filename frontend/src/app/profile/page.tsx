"use client";

import { Save } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { profileIssues } from "@/lib/profile";
import { roleLabel } from "@/lib/labels";
import type { User } from "@/types/domain";

export default function ProfilePage() {
  return (
    <AuthGuard roles={["student", "teacher", "operator", "admin"]}>
      <AppShell>
        <ProfileWorkspace />
      </AppShell>
    </AuthGuard>
  );
}

function ProfileWorkspace() {
  const { user, reload } = useAuth();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [studentGroup, setStudentGroup] = useState(user?.student_group ?? "");
  const [studentGroups, setStudentGroups] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setFullName(user?.full_name ?? "");
    setStudentGroup(user?.student_group ?? "");
  }, [user]);

  useEffect(() => {
    if (user?.role !== "student") return;
    async function loadGroups() {
      try {
        setStudentGroups(await apiRequest<string[]>("/users/student-groups"));
      } catch {
        setStudentGroups([]);
      }
    }
    void loadGroups();
  }, [user?.role]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setSaving(true);
    try {
      await apiRequest<User>("/users/me/profile", {
        method: "PATCH",
        body: {
          full_name: fullName,
          student_group: user?.role === "student" ? studentGroup : null,
        },
      });
      await reload();
      setSuccess("Профіль збережено.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не вдалося зберегти профіль.");
    } finally {
      setSaving(false);
    }
  }

  const issues = profileIssues(user);

  return (
    <>
      <div className="section-title">
        <div>
          <h1>Профіль</h1>
          <p className="muted">Ці дані потрібні, щоб система знала, хто створює або обробляє заявку.</p>
        </div>
      </div>

      <section className="panel profile-panel">
        {issues.length > 0 && (
          <div className="info-box">
            Перед роботою із заявками потрібно: {issues.join("; ")}.
          </div>
        )}
        {error && <div className="error-box">{error}</div>}
        {success && <div className="info-box">{success}</div>}

        <form className="profile-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>Роль</span>
            <input disabled value={user ? roleLabel[user.role] : ""} />
          </label>
          <label className="field">
            <span>Прізвище ім&apos;я по батькові</span>
            <input
              autoComplete="name"
              onChange={(event) => setFullName(event.target.value)}
              placeholder="Наприклад: Петренко Іван Сергійович"
              required
              value={fullName}
            />
          </label>
          {user?.role === "student" && (
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
          <button className="primary-button" disabled={saving} type="submit">
            <Save size={18} />
            {saving ? "Збереження..." : "Зберегти профіль"}
          </button>
        </form>
      </section>
    </>
  );
}
