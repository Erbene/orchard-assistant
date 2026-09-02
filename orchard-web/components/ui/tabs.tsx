"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/** Minimal controlled tabs (no Radix dependency). */

interface TabsCtx {
  value: string;
  setValue: (v: string) => void;
}
const Ctx = React.createContext<TabsCtx | null>(null);

export function Tabs({
  value,
  onValueChange,
  children,
  className,
}: {
  value: string;
  onValueChange: (v: string) => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Ctx.Provider value={{ value, setValue: onValueChange }}>
      <div className={className}>{children}</div>
    </Ctx.Provider>
  );
}

export function TabsList({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="tablist"
      className="inline-flex h-9 items-center gap-1 rounded-lg bg-muted p-1 text-muted-foreground"
    >
      {children}
    </div>
  );
}

export function TabsTrigger({
  value,
  children,
}: {
  value: string;
  children: React.ReactNode;
}) {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("TabsTrigger must be inside <Tabs>");
  const active = ctx.value === value;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={() => ctx.setValue(value)}
      className={cn(
        "inline-flex items-center rounded-md px-3 py-1 text-sm font-medium transition-colors",
        active
          ? "bg-background text-foreground shadow-sm"
          : "hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({
  value,
  children,
  className,
}: {
  value: string;
  children: React.ReactNode;
  className?: string;
}) {
  const ctx = React.useContext(Ctx);
  if (!ctx || ctx.value !== value) return null;
  return (
    <div role="tabpanel" className={className}>
      {children}
    </div>
  );
}
