"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";
import type { UserRole } from "@/types/domain";

export function AuthGuard({
  roles,
  children,
}: {
  roles?: UserRole[];
  children: React.ReactNode;
}) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    } else if (!loading && user && roles && !roles.includes(user.role)) {
      router.replace(user.role === "operator" || user.role === "admin" ? "/operator" : "/tickets");
    }
  }, [loading, user, roles, router]);

  if (loading || !user || (roles && !roles.includes(user.role))) {
    return <main className="center-screen">Завантаження...</main>;
  }

  return <>{children}</>;
}

