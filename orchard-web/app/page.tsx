"use client";

import * as React from "react";
import { Sprout, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EntityManager } from "@/components/crud/entity-manager";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { cn } from "@/lib/utils";

/**
 * Dual-mode dashboard:
 *  - left / center : manual form-based CRUD for zones and trees
 *  - right         : AI assistant (fixed sidebar on lg+, slide-over drawer below)
 */
export default function DashboardPage() {
  const [chatOpen, setChatOpen] = React.useState(false);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="flex items-center gap-3 border-b bg-card px-4 py-3">
        <span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Sprout className="size-5" />
        </span>
        <div className="flex-1">
          <h1 className="text-sm font-semibold leading-tight">
            Orchard Management System
          </h1>
          <p className="text-xs text-muted-foreground">
            Manual records · AI assistant
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="lg:hidden"
          onClick={() => setChatOpen(true)}
        >
          <MessageSquare className="size-4" /> Assistant
        </Button>
      </header>

      <div className="grid flex-1 overflow-hidden lg:grid-cols-[minmax(0,1fr)_420px]">
        <main className="overflow-hidden p-4">
          <EntityManager />
        </main>

        {/* Desktop: persistent sidebar */}
        <aside className="hidden overflow-hidden lg:block">
          <ChatDrawer />
        </aside>
      </div>

      {/* Mobile / tablet: slide-over drawer */}
      <div
        className={cn(
          "fixed inset-0 z-50 lg:hidden",
          chatOpen ? "pointer-events-auto" : "pointer-events-none",
        )}
        aria-hidden={!chatOpen}
      >
        <div
          className={cn(
            "absolute inset-0 bg-black/40 transition-opacity",
            chatOpen ? "opacity-100" : "opacity-0",
          )}
          onClick={() => setChatOpen(false)}
        />
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Orchard assistant"
          className={cn(
            "absolute right-0 top-0 h-full w-[90%] max-w-[420px] bg-card shadow-xl transition-transform",
            chatOpen ? "translate-x-0" : "translate-x-full",
          )}
        >
          <ChatDrawer onClose={() => setChatOpen(false)} />
        </div>
      </div>
    </div>
  );
}
