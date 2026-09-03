"use client";

import * as React from "react";
import { FlaskConical, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError, irrigationApi } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import type { DemoCatalog, IrrigationActionType } from "@/lib/types";

const ACTION_LABEL: Record<IrrigationActionType, string> = {
  skip_schedule: "Skip schedule",
  adjust_duration: "Adjust duration",
  start_zone_watering: "Emergency run",
  pass_no_action: "Pass (baseline)",
};

export function DemoScenarios({ onApplied }: { onApplied?: () => void }) {
  const toast = useToast();
  const [catalog, setCatalog] = React.useState<DemoCatalog | null>(null);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [applying, setApplying] = React.useState(false);

  const load = React.useCallback(async () => {
    const cat = await irrigationApi.demoCatalog();
    setCatalog(cat);
    setSelected(cat.active_scenario_id);
  }, []);

  React.useEffect(() => {
    void load().catch(() => setCatalog(null));
  }, [load]);

  async function apply() {
    if (!selected) return;
    setApplying(true);
    try {
      const res = await irrigationApi.applyDemo(selected);
      toast.success("Demo scenario pinned", res.message);
      await load();
      onApplied?.();
    } catch (err) {
      toast.error(
        "Could not apply scenario",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setApplying(false);
    }
  }

  if (!catalog) {
    return (
      <div className="flex items-center gap-2 border-b px-6 py-3 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Loading demo scenarios…
      </div>
    );
  }

  return (
    <section className="border-b px-6 py-4">
      <div className="mx-auto max-w-2xl space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <FlaskConical className="size-4 text-primary" />
            Demo scenarios
          </h2>
          {catalog.active_scenario_id && (
            <span className="rounded-full border bg-muted/50 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              Active: {catalog.active_scenario_id}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          Pin stub readings for a known supervisor outcome, then click{" "}
          <strong>Run Supervision Task</strong> (LangSmith records{" "}
          <code className="text-[11px]">irrigation.tot_solver</code>).
        </p>

        <div className="space-y-2" role="radiogroup" aria-label="Demo scenario">
          {catalog.scenarios.map((scenario) => {
            const checked = selected === scenario.id;
            const active = catalog.active_scenario_id === scenario.id;
            return (
              <label
                key={scenario.id}
                className={cn(
                  "flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors",
                  checked ? "border-primary ring-1 ring-primary/30" : "border-border",
                  active && !checked && "bg-muted/30",
                )}
              >
                <input
                  type="radio"
                  name="demo-scenario"
                  value={scenario.id}
                  checked={checked}
                  onChange={() => setSelected(scenario.id)}
                  className="mt-1 shrink-0"
                />
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{scenario.title}</span>
                    <span className="rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                      {ACTION_LABEL[scenario.expected_action as IrrigationActionType] ??
                        scenario.expected_action}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground">{scenario.summary}</p>
                  {scenario.detail && (
                    <p className="text-xs text-muted-foreground/80">{scenario.detail}</p>
                  )}
                </div>
              </label>
            );
          })}
        </div>

        <Button
          size="sm"
          disabled={!selected || applying}
          onClick={() => void apply()}
          className="gap-1.5"
        >
          {applying ? (
            <>
              <Loader2 className="size-4 animate-spin" /> Applying…
            </>
          ) : (
            "Apply scenario"
          )}
        </Button>
      </div>
    </section>
  );
}
