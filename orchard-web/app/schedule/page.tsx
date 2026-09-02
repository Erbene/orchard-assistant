"use client";

import * as React from "react";
import { CalendarClock, Loader2 } from "lucide-react";
import { useToast } from "@/components/ui/toast";
import { TimeStep } from "@/components/schedule/time-step";
import { ResourceStep } from "@/components/schedule/resource-step";
import { ScheduleList } from "@/components/schedule/schedule-list";
import { ApiError, scheduleApi } from "@/lib/api";
import type { ScheduleState } from "@/lib/types";

export default function SchedulePage() {
  const toast = useToast();
  const [state, setState] = React.useState<ScheduleState | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  async function run(fn: () => Promise<ScheduleState>) {
    setSubmitting(true);
    try {
      setState(await fn());
    } catch (err) {
      toast.error(
        "Scheduling failed",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSubmitting(false);
    }
  }

  const step = state?.step ?? "need_time";

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-6 py-4">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <CalendarClock className="size-5" /> JIT Schedule
        </h1>
        <p className="text-sm text-muted-foreground">
          Negotiate today&rsquo;s work session with the Foreman.
        </p>
      </header>

      <div className="flex-1 overflow-auto p-6">
        {submitting && !state ? (
          <div className="flex justify-center py-16">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : step === "need_time" ? (
          <TimeStep
            submitting={submitting}
            onSubmit={(minutes) =>
              run(() =>
                state
                  ? scheduleApi.resumeTime(state.thread_id, minutes)
                  : scheduleApi.plan(minutes),
              )
            }
          />
        ) : step === "need_resources" && state ? (
          <ResourceStep
            resources={state.required_resources}
            submitting={submitting}
            onSubmit={(have) =>
              run(() => scheduleApi.resumeResources(state.thread_id, have))
            }
          />
        ) : state ? (
          <ScheduleList state={state} onRestart={() => setState(null)} />
        ) : null}
      </div>
    </div>
  );
}
