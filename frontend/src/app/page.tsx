"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";

export default function HomePage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
    } else if (user.role === "operator" || user.role === "admin") {
      router.replace("/operator");
    } else {
      router.replace("/tickets");
    }
  }, [loading, router, user]);

  return <main className="center-screen">Завантаження...</main>;
}

