"use client";

import * as React from "react";
import {
  CalendarClock,
  CheckCircle2,
  Clock,
  History,
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
import { TaskMetaPills } from "@/components/schedule/task-meta";
import { ApiError, scheduleApi, tasksApi } from "@/lib/api";
import type { ExecutedTask, InboxTask, ScheduleState } from "@/lib/types";

export default function SchedulePage() {
  const toast = useToast();
  const [tab, setTab] = React.useState<"inbox" | "history">("inbox");
  const [tasks, setTasks] = React.useState<InboxTask[] | null>(null);
  const [history, setHistory] = React.useState<ExecutedTask[] | null>(null);
  const [planOpen, setPlanOpen] = React.useState(false);
  const [pendingId, setPendingId] = React.useState<number | null>(null);

  const loadInbox = React.useCallback(() => {
    tasksApi
      .list()
      .then(setTasks)
      .catch(() => setTasks([]));
  }, []);

  const loadHistory = React.useCallback(() => {
    tasksApi
      .history()
      .then(setHistory)
      .catch(() => setHistory([]));
  }, []);

  const load = React.useCallback(() => {
    loadInbox();
    loadHistory();
  }, [loadInbox, loadHistory]);

  React.useEffect(() => {
    load();
  }, [load]);

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

      <div className="border-b px-6">
        <div className="flex gap-1">
          <TabButton active={tab === "inbox"} onClick={() => setTab("inbox")}>
            Inbox
          </TabButton>
          <TabButton active={tab === "history"} onClick={() => setTab("history")}>
            History
          </TabButton>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-2xl">
          {tab === "history" ? (
            <HistoryPanel rows={history} />
          ) : tasks === null ? (
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

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "flex items-center border-b-2 px-3 py-2.5 text-sm font-medium transition-colors " +
        (active
          ? "border-primary text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground")
      }
    >
      {children}
    </button>
  );
}

function HistoryPanel({ rows }: { rows: ExecutedTask[] | null }) {
  if (rows === null) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed py-16 text-center text-sm text-muted-foreground">
        No completed work recorded yet.
      </div>
    );
  }
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.id} className="rounded-lg border p-3">
          <div className="flex items-center gap-2">
            <History className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate text-sm font-medium">{row.action_type}</span>
          </div>
          <TaskMetaPills
            treeSpecies={row.tree_species}
            treeVariety={row.tree_variety}
            treeId={row.tree_id}
            category={row.category}
            estimatedMinutes={row.estimated_minutes}
            completedAt={row.executed_at}
            resources={row.required_resources}
          />
        </li>
      ))}
    </ul>
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
  const outOfSeason =
    task.out_of_season ||
    (task.window_closes_on != null &&
      (() => {
        const closes = new Date(task.window_closes_on);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        closes.setHours(0, 0, 0, 0);
        return closes.getTime() < today.getTime();
      })());
  const overdue =
    !outOfSeason &&
    task.scheduled_date != null &&
    new Date(task.scheduled_date) < new Date();
  const windowClosing =
    !outOfSeason &&
    task.window_closes_on != null &&
    (() => {
      const closes = new Date(task.window_closes_on);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      closes.setHours(0, 0, 0, 0);
      const days = Math.round(
        (closes.getTime() - today.getTime()) / (1000 * 60 * 60 * 24),
      );
      return days >= 0 && days < 14;
    })();

  const resourceLabels = task.template_resource_plan.map(
    (r) => `${r.quantity} ${r.unit} ${r.name}`,
  );

  return (
    <li className="flex items-start gap-3 rounded-lg border p-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium">
            {task.action_type}
          </span>
        </div>
        <TaskMetaPills
          treeSpecies={task.tree_species}
          treeVariety={task.tree_variety}
          treeId={task.tree_id}
          category={task.template_category}
          estimatedMinutes={task.estimated_minutes}
          due={due}
          overdue={overdue}
          outOfSeason={outOfSeason}
          windowClosing={windowClosing}
          windowClosesOn={task.window_closes_on}
          lastCompleted={task.last_completed}
          resources={resourceLabels}
          priority={task.priority_score}
        />
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
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCompleted();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-2xl">
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
            <ScheduleList
              state={state}
              onRestart={() => setState(null)}
              onTasksCompleted={onCompleted}
            />
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
