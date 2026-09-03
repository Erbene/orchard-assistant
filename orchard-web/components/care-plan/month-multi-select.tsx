"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export const MONTH_LABELS = [
  "J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D",
];

export function MonthMultiSelect({
  label,
  selected,
  onChange,
  id,
}: {
  label: string;
  selected: number[];
  onChange: (months: number[]) => void;
  id?: string;
}) {
  const set = new Set(selected);

  function toggle(month: number) {
    const next = new Set(set);
    if (next.has(month)) {
      next.delete(month);
    } else if (next.size < 4) {
      next.add(month);
    }
    onChange([...next].sort((a, b) => a - b));
  }

  return (
    <div className="space-y-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div
        id={id}
        className="grid grid-cols-12 gap-0.5"
        role="group"
        aria-label={label}
      >
        {MONTH_LABELS.map((name, i) => {
          const month = i + 1;
          const on = set.has(month);
          return (
            <button
              key={month}
              type="button"
              aria-pressed={on}
              title={name}
              className={cn(
                "rounded px-0.5 py-1.5 text-center text-[10px] transition-colors",
                on
                  ? "bg-primary text-primary-foreground ring-1 ring-primary"
                  : "bg-muted/40 text-muted-foreground hover:bg-muted",
              )}
              onClick={() => toggle(month)}
            >
              {name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function phenologyListsFromTree(tree: {
  expected_flowering_months?: number[];
  expected_harvest_months?: number[];
  expected_dormancy_months?: number[];
  expected_flowering_month?: number | null;
  expected_harvest_month?: number | null;
  expected_dormancy_month?: number | null;
}): { flowering: number[]; harvest: number[]; dormancy: number[] } {
  const flowering =
    tree.expected_flowering_months?.length
      ? tree.expected_flowering_months
      : tree.expected_flowering_month != null
        ? [tree.expected_flowering_month]
        : [];
  const harvest =
    tree.expected_harvest_months?.length
      ? tree.expected_harvest_months
      : tree.expected_harvest_month != null
        ? [tree.expected_harvest_month]
        : [];
  const dormancy =
    tree.expected_dormancy_months?.length
      ? tree.expected_dormancy_months
      : tree.expected_dormancy_month != null
        ? [tree.expected_dormancy_month]
        : [];
  return { flowering, harvest, dormancy };
}

export function phenologyListsFromRead(phenology: {
  flowering_months?: number[];
  harvest_months?: number[];
  dormancy_months?: number[];
  flowering_month?: number | null;
  harvest_month?: number | null;
  dormancy_month?: number | null;
}): { flowering: number[]; harvest: number[]; dormancy: number[] } {
  const flowering =
    phenology.flowering_months?.length
      ? phenology.flowering_months
      : phenology.flowering_month != null
        ? [phenology.flowering_month]
        : [];
  const harvest =
    phenology.harvest_months?.length
      ? phenology.harvest_months
      : phenology.harvest_month != null
        ? [phenology.harvest_month]
        : [];
  const dormancy =
    phenology.dormancy_months?.length
      ? phenology.dormancy_months
      : phenology.dormancy_month != null
        ? [phenology.dormancy_month]
        : [];
  return { flowering, harvest, dormancy };
}
