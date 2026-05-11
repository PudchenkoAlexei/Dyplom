import type { User } from "@/types/domain";

export function profileIssues(user: User | null): string[] {
  if (!user) return [];

  const issues: string[] = [];
  if (user.full_name.trim().split(/\s+/).length < 3) {
    issues.push("заповніть прізвище, ім'я та по батькові");
  }
  if (user.role === "student" && !user.student_group?.trim()) {
    issues.push("виберіть академічну групу");
  }
  return issues;
}

export function isProfileComplete(user: User | null): boolean {
  return profileIssues(user).length === 0;
}
