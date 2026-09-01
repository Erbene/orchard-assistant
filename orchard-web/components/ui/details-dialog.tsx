"use client";

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export type DetailField = [label: string, value: React.ReactNode];

interface DetailsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  /** Compact metadata rows shown at the top (2-up on desktop). */
  fields: DetailField[];
  /** Optional full-width block below the fields (e.g. rendered content). */
  content?: React.ReactNode;
  /** Width override, e.g. "sm:max-w-3xl". Defaults to "sm:max-w-2xl". */
  className?: string;
}

export function DetailsDialog({
  open,
  onOpenChange,
  title,
  description,
  fields,
  content,
  className,
}: DetailsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn("sm:max-w-2xl", className)}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
          {fields.map(([label, value]) => (
            <div key={label} className="min-w-0 space-y-0.5">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {label}
              </dt>
              <dd className="break-words leading-relaxed">
                {value === null || value === undefined || value === "" ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  value
                )}
              </dd>
            </div>
          ))}
        </dl>

        {content}
      </DialogContent>
    </Dialog>
  );
}
