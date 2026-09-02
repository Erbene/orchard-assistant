"use client";

import * as React from "react";
import { Check, Loader2, PackageCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function ResourceStep({
  resources,
  onSubmit,
  submitting,
}: {
  resources: string[];
  onSubmit: (have: string[]) => void;
  submitting: boolean;
}) {
  const [have, setHave] = React.useState<Set<string>>(() => new Set(resources));

  function toggle(r: string) {
    setHave((prev) => {
      const next = new Set(prev);
      if (next.has(r)) next.delete(r);
      else next.add(r);
      return next;
    });
  }

  return (
    <div className="mx-auto max-w-md space-y-5">
      <div className="space-y-1 text-center">
        <PackageCheck className="mx-auto size-6 text-muted-foreground" />
        <h2 className="text-lg font-semibold">Do you have these on hand?</h2>
        <p className="text-sm text-muted-foreground">
          Anything you uncheck gets dropped and the time is backfilled with
          other work.
        </p>
      </div>

      <ul className="space-y-2">
        {resources.map((r) => {
          const on = have.has(r);
          return (
            <li key={r}>
              <button
                type="button"
                onClick={() => toggle(r)}
                aria-pressed={on}
                className={cn(
                  "flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left text-sm transition-colors",
                  on ? "border-primary/40 bg-primary/5" : "hover:bg-accent",
                )}
              >
                <span
                  className={cn(
                    "flex size-5 shrink-0 items-center justify-center rounded border",
                    on
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-input",
                  )}
                >
                  {on && <Check className="size-3.5" />}
                </span>
                {r}
              </button>
            </li>
          );
        })}
      </ul>

      <Button
        className="w-full"
        disabled={submitting}
        onClick={() => onSubmit([...have])}
      >
        {submitting && <Loader2 className="size-4 animate-spin" />}
        Confirm &amp; build schedule
      </Button>
    </div>
  );
}
