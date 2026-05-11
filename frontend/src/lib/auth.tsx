"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiRequest } from "@/lib/api";
import type { User, UserRole } from "@/types/domain";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    student_group?: string | null;
    role: UserRole;
  }) => Promise<User>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const currentUser = await apiRequest<User>("/auth/me");
      setUser(currentUser);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const login = useCallback(async (email: string, password: string) => {
    const currentUser = await apiRequest<User>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    setUser(currentUser);
    return currentUser;
  }, []);

  const register = useCallback(
    async (payload: {
      email: string;
      password: string;
      full_name: string;
      student_group?: string | null;
      role: UserRole;
    }) => {
      const currentUser = await apiRequest<User>("/auth/register", {
        method: "POST",
        body: payload,
      });
      setUser(currentUser);
      return currentUser;
    },
    [],
  );

  const logout = useCallback(async () => {
    await apiRequest<{ message: string }>("/auth/logout", { method: "POST" });
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout, reload }),
    [user, loading, login, register, logout, reload],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return context;
}
