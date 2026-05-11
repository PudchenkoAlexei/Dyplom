import { roleLabel } from "@/lib/labels";
import type { User } from "@/types/domain";

export function requesterSummary(user?: User | null): string {
  if (!user) return "Заявник не визначений";
  const role = roleLabel[user.role];
  const group = user.role === "student" && user.student_group ? `, група ${user.student_group}` : "";
  return `${user.full_name} (${role}${group})`;
}

export function RequesterMeta({ user }: { user?: User | null }) {
  if (!user) {
    return (
      <div className="meta-item">
        <span>Заявник</span>
        <strong>Не визначено</strong>
      </div>
    );
  }

  return (
    <div className="meta-item">
      <span>Заявник</span>
      <strong>{user.full_name}</strong>
      <small>
        {roleLabel[user.role]}
        {user.role === "student" && user.student_group ? ` - ${user.student_group}` : ""}
      </small>
    </div>
  );
}
