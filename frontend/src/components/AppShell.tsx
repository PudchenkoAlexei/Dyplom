"use client";

import { BookOpen, ClipboardList, Headphones, LogOut, ShieldCheck, Ticket, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth";
import { roleLabel } from "@/lib/labels";

const navItems = [
  { href: "/admin/knowledge", label: "База знань", icon: BookOpen, roles: ["admin"] },
  { href: "/assistant", label: "Довідкова", icon: Headphones, roles: ["student", "teacher"] },
  { href: "/tickets", label: "Мої заявки", icon: Ticket, roles: ["student", "teacher"] },
  { href: "/operator", label: "Черга заявок", icon: ClipboardList, roles: ["operator", "admin"] },
  { href: "/profile", label: "Профіль", icon: UserRound, roles: ["student", "teacher", "operator", "admin"] },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <div className="app-frame">
      <aside className="sidebar">
        <div className="brand">
          <ShieldCheck size={24} />
          <div>
            <strong>KPI Helpdesk</strong>
            <span>Голосові звернення</span>
          </div>
        </div>

        <nav className="nav-list">
          {navItems
            .filter((item) => user && item.roles.includes(user.role))
            .map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  className={pathname === item.href ? "nav-link active" : "nav-link"}
                  href={item.href}
                  key={item.href}
                >
                  <Icon size={18} />
                  {item.label}
                </Link>
              );
            })}
        </nav>

        <div className="profile-block">
          <div>
            <strong>{user?.full_name}</strong>
            <span>{user ? `${roleLabel[user.role]}${user.student_group ? ` - ${user.student_group}` : ""}` : ""}</span>
          </div>
          <button className="icon-button" onClick={handleLogout} title="Вийти" type="button">
            <LogOut size={18} />
          </button>
        </div>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  );
}
