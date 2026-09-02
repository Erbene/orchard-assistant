"use client";

import * as React from "react";
import { Clock, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const PRESETS: { label: string; minutes: number }[] = [
  { label: "1 Hour", minutes: 60 },
  { label: "Half Day", minutes: 240 },
  { label: "Full Day", minutes: 480 },
];

export function TimeStep({
  onSubmit,
  submitting,
}: {
  onSubmit: (minutes: number) => void;
  submitting: boolean;
}) {
  const [minutes, setMinutes] = React.useState(60);

  return (
    <div className="mx-auto max-w-md space-y-5">
      <div className="space-y-1 text-center">
        <Clock className="mx-auto size-6 text-muted-foreground" />
        <h2 className="text-lg font-semibold">How much time do you have?</h2>
        <p className="text-sm text-muted-foreground">
          The Foreman packs your highest-priority tasks into this window.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.minutes}
            type="button"
            onClick={() => setMinutes(p.minutes)}
            className={cn(
              "rounded-md border px-3 py-3 text-sm font-medium transition-colors",
              minutes === p.minutes
                ? "border-primary bg-primary/10 text-primary"
                : "hover:bg-accent",
            )}
          >
            {p.label}
            <span className="block text-xs font-normal text-muted-foreground">
              {p.minutes} min
            </span>
          </button>
        ))}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">or exactly</span>
        <Input
          type="number"
          min={5}
          max={1440}
          value={minutes}
          onChange={(e) =>
            setMinutes(Math.max(5, Math.min(1440, Number(e.target.value) || 5)))
          }
          className="w-24"
        />
        <span className="text-muted-foreground">minutes</span>
      </label>

      <Button
        className="w-full"
        disabled={submitting}
        onClick={() => onSubmit(minutes)}
      >
        {submitting && <Loader2 className="size-4 animate-spin" />}
        Plan My Session
      </Button>
    </div>
  );
}
