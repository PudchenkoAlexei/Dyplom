import { UserRound } from "lucide-react";
import Link from "next/link";

export function ProfileRequired({ issues }: { issues: string[] }) {
  return (
    <section className="panel profile-required">
      <div>
        <h2>Заповніть профіль</h2>
        <p className="muted">
          Робота із заявками буде доступна після заповнення обов&apos;язкових даних:{" "}
          {issues.join("; ")}.
        </p>
      </div>
      <Link className="primary-button" href="/profile">
        <UserRound size={18} />
        Перейти до профілю
      </Link>
    </section>
  );
}
