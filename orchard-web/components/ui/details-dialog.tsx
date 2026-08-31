"use client";

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export type DetailField = [label: string, value: React.ReactNode];

interface DetailsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  fields: DetailField[];
}

export function DetailsDialog({
  open,
  onOpenChange,
  title,
  fields,
}: DetailsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <dl className="divide-y text-sm">
          {fields.map(([label, value]) => (
            <div key={label} className="grid grid-cols-3 gap-3 py-2">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="col-span-2 break-words">
                {value === null || value === undefined || value === "" ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  value
                )}
              </dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  );
}
