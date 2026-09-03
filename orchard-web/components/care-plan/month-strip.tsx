"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { MONTH_LABELS } from "./month-multi-select";

function cutoffMonthsFromOffset(
  anchorMonths: number[],
  offsetDays: number,
): Set<number> {
  const out = new Set<number>();
  if (offsetDays >= 0) return out;
  for (const anchorMonth of anchorMonths) {
    const d = new Date(2024, anchorMonth - 1, 1);
    d.setDate(d.getDate() + offsetDays);
    out.add(d.getMonth() + 1);
  }
  return out;
}

export function MonthStrip({
  validMonths,
  anchorMonth,
  anchorMonths,
  anchorOffsetDays,
  className,
}: {
  validMonths: number[];
  anchorMonth?: number | null;
  anchorMonths?: number[];
  anchorOffsetDays?: number | null;
  className?: string;
}) {
  const valid = new Set(validMonths);
  const anchors = new Set(
    anchorMonths?.length
      ? anchorMonths
      : anchorMonth != null
        ? [anchorMonth]
        : [],
  );
  const cutoffMonths =
    anchors.size > 0 && anchorOffsetDays != null && anchorOffsetDays < 0
      ? cutoffMonthsFromOffset([...anchors], anchorOffsetDays)
      : new Set<number>();

  return (
    <div
      className={cn("grid grid-cols-12 gap-0.5 text-center text-[10px]", className)}
      aria-label="Seasonal window"
    >
      {MONTH_LABELS.map((label, i) => {
        const month = i + 1;
        const isValid = valid.has(month);
        const isAnchor = anchors.has(month);
        const isCutoff = cutoffMonths.has(month);
        return (
          <div
            key={month}
            className={cn(
              "rounded px-0.5 py-1 text-muted-foreground",
              isValid && "bg-primary/20 font-medium text-foreground",
              isAnchor && "ring-1 ring-primary",
              isCutoff && "border-b-2 border-amber-500",
            )}
            title={
              isAnchor
                ? `Anchor month (${label})`
                : isCutoff
                  ? "Safety cutoff window"
                  : isValid
                    ? `Valid month (${label})`
                    : label
            }
          >
            {label}
          </div>
        );
      })}
    </div>
  );
}

export function constraintCaption(template: {
  interval_days: number;
  valid_months: number[];
  biological_anchor?: string | null;
  anchor_offset_days?: number | null;
}): string | null {
  const parts: string[] = [`every ${template.interval_days} days`];
  if (template.valid_months.length > 0) {
    const names = template.valid_months
      .slice()
      .sort((a, b) => a - b)
      .map((m) => MONTH_LABELS[m - 1])
      .join(", ");
    parts.push(`in ${names}`);
  }
  if (template.biological_anchor && template.anchor_offset_days != null) {
    parts.push(
      `halt ${Math.abs(template.anchor_offset_days)}d before ${template.biological_anchor}`,
    );
  }
  if (parts.length === 1 && !template.biological_anchor) return null;
  return parts.join("; ");
}
