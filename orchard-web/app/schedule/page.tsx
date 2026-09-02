"use client";

import * as React from "react";
import {
  CalendarClock,
  CheckCircle2,
  Clock,
  Loader2,
  SkipForward,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { TimeStep } from "@/components/schedule/time-step";
import { ResourceStep } from "@/components/schedule/resource-step";
import { ScheduleList } from "@/components/schedule/schedule-list";
import { ApiError, scheduleApi, tasksApi } from "@/lib/api";
import type { InboxTask, ScheduleState } from "@/lib/types";

export default function SchedulePage() {
  const toast = useToast();
  const [tasks, setTasks] = React.useState<InboxTask[] | null>(null);
  const [planOpen, setPlanOpen] = React.useState(false);
  const [pendingId, setPendingId] = React.useState<number | null>(null);

  const load = React.useCallback(() => {
    tasksApi
      .list()
      .then(setTasks)
      .catch(() => setTasks([]));
  }, []);

  React.useEffect(() => load(), [load]);

  async function act(id: number, fn: () => Promise<unknown>, verb: string) {
    setPendingId(id);
    try {
      await fn();
      toast.success(`Task ${verb}`);
      load();
    } catch (err) {
      toast.error(
        `Could not ${verb === "completed" ? "complete" : "skip"} the task`,
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b px-6 py-4">
        <div className="flex-1">
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <CalendarClock className="size-5" /> Schedule
          </h1>
          <p className="text-sm text-muted-foreground">
            Your generated task inbox. Start a Just-In-Time session to fit them
            into the time you have.
          </p>
        </div>
        <Button onClick={() => setPlanOpen(true)} className="gap-1.5">
          <Clock className="size-4" />
          Plan a work session
        </Button>
      </header>

      <div className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-2xl">
          {tasks === null ? (
            <div className="flex justify-center py-16">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : tasks.length === 0 ? (
            <div className="rounded-lg border border-dashed py-16 text-center text-sm text-muted-foreground">
              No pending tasks. Generate a Care Plan on a tree to populate this
              inbox.
            </div>
          ) : (
            <ul className="space-y-2">
              {tasks.map((t) => (
                <TaskRow
                  key={t.id}
                  task={t}
                  busy={pendingId === t.id}
                  onComplete={() =>
                    act(t.id, () => tasksApi.complete(t.id), "completed")
                  }
                  onSkip={() => act(t.id, () => tasksApi.skip(t.id), "skipped")}
                />
              ))}
            </ul>
          )}
        </div>
      </div>

      <PlanSessionDialog
        open={planOpen}
        onOpenChange={setPlanOpen}
        onCompleted={load}
      />
    </div>
  );
}

// --------------------------------------------------------------------------

function TaskRow({
  task,
  busy,
  onComplete,
  onSkip,
}: {
  task: InboxTask;
  busy: boolean;
  onComplete: () => void;
  onSkip: () => void;
}) {
  const due = task.scheduled_date
    ? new Date(task.scheduled_date).toLocaleDateString()
    : "unscheduled";
  const overdue =
    task.scheduled_date != null && new Date(task.scheduled_date) < new Date();

  return (
    <li className="flex items-start gap-3 rounded-lg border p-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {task.template_category && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium uppercase text-muted-foreground">
              {task.template_category}
            </span>
          )}
          <span className="truncate text-sm font-medium">
            {task.action_type}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {task.tree_species} · {task.tree_variety} · pri{" "}
          {task.priority_score.toFixed(1)}
          {task.estimated_minutes ? ` · ~${task.estimated_minutes} min` : ""}
          {" · "}
          <span className={overdue ? "font-medium text-destructive" : ""}>
            {overdue ? "overdue" : `due ${due}`}
          </span>
        </p>
        {task.template_resource_plan.length > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">
            {task.template_resource_plan
              .map((r) => `${r.quantity} ${r.unit} ${r.name}`)
              .join(" · ")}
          </p>
        )}
      </div>
      <div className="flex shrink-0 gap-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Skip task"
          disabled={busy}
          onClick={onSkip}
          className="text-muted-foreground"
        >
          <SkipForward className="size-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Mark complete"
          disabled={busy}
          onClick={onComplete}
          className="text-success"
        >
          {busy ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <CheckCircle2 className="size-4" />
          )}
        </Button>
      </div>
    </li>
  );
}

// --------------------------------------------------------------------------

function PlanSessionDialog({
  open,
  onOpenChange,
  onCompleted,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onCompleted: () => void;
}) {
  const toast = useToast();
  const [state, setState] = React.useState<ScheduleState | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    if (!open) {
      setState(null);
      setSubmitting(false);
    }
  }, [open]);

  async function run(fn: () => Promise<ScheduleState>) {
    setSubmitting(true);
    try {
      const next = await fn();
      setState(next);
      if (next.step === "done") onCompleted();
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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Plan a work session</DialogTitle>
        </DialogHeader>

        <div className="py-2">
          {submitting && !state ? (
            <div className="flex justify-center py-12">
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
      </DialogContent>
    </Dialog>
  );
}
