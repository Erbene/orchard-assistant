import type { Metadata } from "next";
import "./globals.css";
import { ToastProvider } from "@/components/ui/toast";
import { Sidebar, MobileHeader } from "@/components/sidebar";

export const metadata: Metadata = {
  title: "Orchard Management System",
  description:
    "Manage orchard zones and trees, and talk to the orchard assistant.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased">
        <ToastProvider>
          <div className="flex h-dvh overflow-hidden">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <MobileHeader />
              <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
            </div>
          </div>
        </ToastProvider>
      </body>
    </html>
  );
}
