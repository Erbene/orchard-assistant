"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  CalendarClock,
  Droplets,
  Library,
  Trees,
  MapPin,
  Menu,
  PanelLeft,
  PanelLeftClose,
  Sprout,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

type NavLeaf = { href: string; label: string; icon: LucideIcon };
type NavGroup = { label: string; icon: LucideIcon; children: readonly NavLeaf[] };
type NavEntry = NavLeaf | NavGroup;

function isGroup(item: NavEntry): item is NavGroup {
  return "children" in item;
}

const NAV: readonly NavEntry[] = [
  { href: "/assistant", label: "Assistant", icon: Bot },
  { href: "/schedule", label: "Schedule", icon: CalendarClock },
  {
    label: "Irrigation",
    icon: Droplets,
    children: [
      { href: "/irrigation", label: "Irrigation planning", icon: Droplets },
      { href: "/zones", label: "Zones", icon: MapPin },
    ],
  },
  { href: "/trees", label: "Trees", icon: Trees },
  { href: "/sources", label: "Sources", icon: Library },
];

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

function NavLink({
  href,
  label,
  icon: Icon,
  collapsed,
  indent,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  collapsed?: boolean;
  indent?: boolean;
  onNavigate?: () => void;
}) {
  const isActive = useIsActive();
  const active = isActive(href);
  return (
    <Link
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
        indent && !collapsed && "pl-9",
      )}
    >
      <Icon className="size-4 shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  );
}

function NavLinks({
  collapsed,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map((item) => {
        if (!isGroup(item)) {
          return (
            <NavLink
              key={item.href}
              href={item.href}
              label={item.label}
              icon={item.icon}
              collapsed={collapsed}
              onNavigate={onNavigate}
            />
          );
        }
        return (
          <div key={item.label} className="flex flex-col gap-0.5">
            {!collapsed && (
              <div className="flex items-center gap-3 px-3 pb-0.5 pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <item.icon className="size-3.5 shrink-0" />
                <span className="truncate">{item.label}</span>
              </div>
            )}
            {item.children.map((child) => (
              <NavLink
                key={child.href}
                href={child.href}
                label={child.label}
                icon={child.icon}
                collapsed={collapsed}
                indent
                onNavigate={onNavigate}
              />
            ))}
          </div>
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
