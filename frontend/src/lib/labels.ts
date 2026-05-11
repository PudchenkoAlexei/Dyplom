import type { Priority, TicketStatus, UserRole } from "@/types/domain";

export const roleLabel: Record<UserRole, string> = {
  student: "Студент",
  teacher: "Викладач",
  operator: "Оператор",
  admin: "Адміністратор",
};

export const statusLabel: Record<TicketStatus, string> = {
  draft: "Чернетка",
  submitted: "Надіслано",
  classified: "Класифіковано",
  in_progress: "В обробці",
  waiting_user: "Очікує уточнення",
  answered: "Відповідь надано",
  closed: "Закрито",
};

export const priorityLabel: Record<Priority, string> = {
  low: "Низький",
  medium: "Середній",
  high: "Високий",
};
