"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  Trees,
  MapPin,
  Menu,
  PanelLeft,
  PanelLeftClose,
  Sprout,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

const NAV = [
  { href: "/assistant", label: "Assistant", icon: Bot },
  { href: "/trees", label: "Trees", icon: Trees },
  { href: "/zones", label: "Zones", icon: MapPin },
] as const;

const STORAGE_KEY = "orchard.sidebar.collapsed";

function useIsActive() {
  const pathname = usePathname();
  return React.useCallback(
    (href: string) =>
      href === "/assistant"
        ? pathname === "/assistant" || pathname === "/"
        : pathname === href || pathname.startsWith(`${href}/`),
    [pathname],
  );
}

function NavLinks({
  collapsed,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const isActive = useIsActive();
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = isActive(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            title={collapsed ? label : undefined}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
              collapsed && "justify-center px-2",
            )}
          >
            <Icon className="size-4 shrink-0" />
            {!collapsed && <span className="truncate">{label}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

function Brand({ collapsed }: { collapsed?: boolean }) {
  return (
    <div
      className={cn(
        "flex h-14 items-center gap-2 border-b px-4",
        collapsed && "justify-center px-2",
      )}
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <Sprout className="size-5" />
      </span>
      {!collapsed && <span className="truncate text-sm font-semibold">Orchard</span>}
    </div>
  );
}

/** Persistent, collapsible sidebar (desktop only). */
export function Sidebar() {
  const [collapsed, setCollapsed] = React.useState(false);

  React.useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      /* private mode / disabled storage */
    }
  }, []);

  const toggle = () =>
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });

  return (
    <aside
      className={cn(
        "hidden shrink-0 flex-col border-r bg-card transition-[width] duration-200 md:flex",
        collapsed ? "w-16" : "w-60",
      )}
    >
      <Brand collapsed={collapsed} />
      <div className="flex-1 overflow-y-auto p-2">
        <NavLinks collapsed={collapsed} />
      </div>
      <div className="border-t p-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={toggle}
          className={cn("w-full justify-center", !collapsed && "justify-start")}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <PanelLeft className="size-4" />
          ) : (
            <>
              <PanelLeftClose className="size-4" /> Collapse
            </>
          )}
        </Button>
      </div>
    </aside>
  );
}

/** Mobile top bar with a slide-out navigation drawer. */
export function MobileHeader() {
  const [open, setOpen] = React.useState(false);
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-card px-2 md:hidden">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" aria-label="Open navigation">
            <Menu className="size-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-64 gap-3">
          <SheetTitle className="flex items-center gap-2">
            <span className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Sprout className="size-4" />
            </span>
            Orchard
          </SheetTitle>
          <NavLinks onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      <span className="text-sm font-semibold">Orchard</span>
    </header>
  );
}
