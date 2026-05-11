import type { Metadata } from "next";

import { AuthProvider } from "@/lib/auth";
import "./styles.css";

export const metadata: Metadata = {
  title: "KPI Voice Helpdesk",
  description: "Система обробки голосових звернень КПІ",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="uk">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}

