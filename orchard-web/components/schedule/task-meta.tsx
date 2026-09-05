"use client";

import {
  AlertTriangle,
  CalendarClock,
  Clock,
  History,
  Package,
  Trees,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { CareCategory } from "@/lib/types";

const CATEGORY_PILL: Record<string, string> = {
  fertilize:
    "border-amber-200 bg-amber-100 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/15 dark:text-amber-300",
  mulch:
    "border-orange-200 bg-orange-100 text-orange-900 dark:border-orange-500/30 dark:bg-orange-500/15 dark:text-orange-300",
  prune:
    "border-violet-200 bg-violet-100 text-violet-800 dark:border-violet-500/30 dark:bg-violet-500/15 dark:text-violet-300",
  scout:
    "border-sky-200 bg-sky-100 text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/15 dark:text-sky-300",
  spray:
    "border-rose-200 bg-rose-100 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/15 dark:text-rose-300",
  irrigation:
    "border-cyan-200 bg-cyan-100 text-cyan-800 dark:border-cyan-500/30 dark:bg-cyan-500/15 dark:text-cyan-300",
  weed:
    "border-lime-200 bg-lime-100 text-lime-800 dark:border-lime-500/30 dark:bg-lime-500/15 dark:text-lime-300",
  stake:
    "border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-500/30 dark:bg-slate-500/15 dark:text-slate-300",
  soil_test:
    "border-indigo-200 bg-indigo-100 text-indigo-800 dark:border-indigo-500/30 dark:bg-indigo-500/15 dark:text-indigo-300",
  other:
    "border-transparent bg-muted text-muted-foreground",
};

const pill =
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium";

export function parseDay(value: string): Date {
  const day = value.slice(0, 10);
  const [y, m, d] = day.split("-").map(Number);
  if (y && m && d) return new Date(y, m - 1, d);
  return new Date(value);
}

export function formatDay(value: string): string {
  return parseDay(value).toLocaleDateString();
}

export function TreePill({
  species,
  variety,
  treeId,
}: {
  species?: string | null;
  variety?: string | null;
  treeId?: number;
}) {
  const label = [species, variety].filter(Boolean).join(" ");
  const text = label || (treeId != null ? `#${treeId}` : null);
  if (!text) return null;
  return (
    <span
      className={cn(
        pill,
        "border-emerald-200 bg-emerald-100 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/15 dark:text-emerald-300",
      )}
    >
      <Trees className="size-3 shrink-0" />
      {text}
    </span>
  );
}

export function CategoryPill({
  category,
}: {
  category?: string | null;
}) {
  if (!category) return null;
  return (
    <span
      className={cn(
        pill,
        "uppercase",
        CATEGORY_PILL[category] ?? CATEGORY_PILL.other,
      )}
    >
      {category.replace(/_/g, " ")}
    </span>
  );
}

export function TaskMetaPills({
  treeSpecies,
  treeVariety,
  treeId,
  category,
  estimatedMinutes,
  due,
  overdue,
  outOfSeason,
  windowClosing,
  windowClosesOn,
  lastCompleted,
  completedAt,
  resources,
  priority,
}: {
  treeSpecies?: string | null;
  treeVariety?: string | null;
  treeId?: number;
  category?: CareCategory | string | null;
  estimatedMinutes?: number | null;
  due?: string | null;
  overdue?: boolean;
  outOfSeason?: boolean;
  windowClosing?: boolean;
  windowClosesOn?: string | null;
  lastCompleted?: string | null;
  completedAt?: string | null;
  resources?: string[];
  priority?: number | null;
}) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      <TreePill species={treeSpecies} variety={treeVariety} treeId={treeId} />
      {category ? <CategoryPill category={category} /> : null}
      {estimatedMinutes ? (
        <span
          className={cn(
            pill,
            "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-500/30 dark:bg-blue-500/15 dark:text-blue-300",
          )}
        >
          <Clock className="size-3 shrink-0" />~{estimatedMinutes} min
        </span>
      ) : null}
      {outOfSeason ? (
        <span className={cn(pill, "border-transparent bg-muted text-muted-foreground")}>
          out of season
        </span>
      ) : overdue ? (
        <span className={cn(pill, "border-destructive/20 bg-destructive/10 text-destructive")}>
          <AlertTriangle className="size-3 shrink-0" />
          overdue
        </span>
      ) : due ? (
        <span
          className={cn(
            pill,
            "border-transparent bg-muted text-muted-foreground",
          )}
        >
          <CalendarClock className="size-3 shrink-0" />
          due {due}
        </span>
      ) : null}
      {windowClosing && windowClosesOn ? (
        <span
          className={cn(
            pill,
            "border-amber-200 bg-amber-100 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/15 dark:text-amber-300",
          )}
        >
          window {formatDay(windowClosesOn)}
        </span>
      ) : null}
      {completedAt ? (
        <span
          className={cn(
            pill,
            "border-teal-200 bg-teal-50 text-teal-800 dark:border-teal-500/30 dark:bg-teal-500/15 dark:text-teal-300",
          )}
        >
          <History className="size-3 shrink-0" />
          {formatDay(completedAt)}
        </span>
      ) : (
        <span
          className={cn(
            pill,
            lastCompleted
              ? "border-teal-200 bg-teal-50 text-teal-800 dark:border-teal-500/30 dark:bg-teal-500/15 dark:text-teal-300"
              : "border-transparent bg-muted text-muted-foreground",
          )}
          title="Last completed"
        >
          <History className="size-3 shrink-0" />
          {lastCompleted ? `Last ${formatDay(lastCompleted)}` : "Never done"}
        </span>
      )}
      {priority != null ? (
        <span className={cn(pill, "border-transparent bg-muted text-muted-foreground")}>
          pri {priority.toFixed(1)}
        </span>
      ) : null}
      {(resources ?? []).map((r) => (
        <span
          key={r}
          className={cn(pill, "border-transparent bg-muted text-muted-foreground")}
        >
          <Package className="size-3 shrink-0" />
          {r}
        </span>
      ))}
    </div>
  );
}
