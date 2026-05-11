import type { Priority, TicketStatus } from "@/types/domain";
import { priorityLabel, statusLabel } from "@/lib/labels";

const statusTone: Record<TicketStatus, string> = {
  draft: "neutral",
  submitted: "info",
  classified: "info",
  in_progress: "warning",
  waiting_user: "warning",
  answered: "success",
  closed: "neutral",
};

const priorityTone: Record<Priority, string> = {
  low: "neutral",
  medium: "info",
  high: "warning",
};

export function StatusBadge({ status }: { status: TicketStatus }) {
  return <span className={`badge ${statusTone[status]}`}>{statusLabel[status]}</span>;
}

export function PriorityBadge({ priority }: { priority: Priority | null }) {
  if (!priority) return <span className="badge neutral">Не визначено</span>;
  return <span className={`badge ${priorityTone[priority]}`}>{priorityLabel[priority]}</span>;
}
