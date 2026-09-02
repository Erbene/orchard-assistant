"use client";

import * as React from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Loader2,
  RotateCcw,
  Send,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { ApiError, scheduleApi } from "@/lib/api";
import type { ScheduleState, ScheduleTask } from "@/lib/types";

export function ScheduleList({
  state,
  onRestart,
}: {
  state: ScheduleState;
  onRestart: () => void;
}) {
  const toast = useToast();
  const [done, setDone] = React.useState<Set<number>>(new Set());
  const [busy, setBusy] = React.useState<number | "report" | null>(null);
  const [report, setReport] = React.useState("");
  const [showDropped, setShowDropped] = React.useState(false);

  async function complete(ids: number[], via: number | "report") {
    setBusy(via);
    try {
      const marked = await scheduleApi.complete(ids);
      setDone((prev) => new Set([...prev, ...marked.map((t) => t.id)]));
      toast.success(`Marked ${marked.length} task(s) complete`);
    } catch (err) {
      toast.error("Could not update", err instanceof ApiError ? err.detail : undefined);
    } finally {
      setBusy(null);
    }
  }

  async function sendReport() {
    if (!report.trim()) return;
    setBusy("report");
    try {
      const res = await scheduleApi.report(report.trim(), state.thread_id);
      setDone((prev) => new Set([...prev, ...res.marked]));
      setReport("");
      toast.success("Foreman updated", res.note);
    } catch (err) {
      toast.error("Could not report", err instanceof ApiError ? err.detail : undefined);
    } finally {
      setBusy(null);
    }
  }

  const totalMin = state.proposed_tasks.reduce(
    (s, t) => s + (t.estimated_minutes ?? 30),
    0,
  );

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Today&rsquo;s session</h2>
          <p className="text-sm text-muted-foreground">
            {state.proposed_tasks.length} task(s) · ~{totalMin} of{" "}
            {state.available_minutes} min
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onRestart}>
          <RotateCcw className="size-3.5" /> New plan
        </Button>
      </div>

      {state.warnings.length > 0 && (
        <div className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          {state.warnings.map((w, i) => (
            <p key={i} className="flex items-start gap-2 text-amber-700 dark:text-amber-400">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              {w}
            </p>
          ))}
        </div>
      )}

      {state.summary && (
        <p className="rounded-md border bg-card p-3 text-sm text-muted-foreground">
          {state.summary}
        </p>
      )}

      <ul className="space-y-2">
        {state.proposed_tasks.map((t) => (
          <TaskRow
            key={t.id}
            task={t}
            done={done.has(t.id)}
            busy={busy === t.id}
            onComplete={() => complete([t.id], t.id)}
          />
        ))}
      </ul>

      {state.dropped_tasks.length > 0 && (
        <div className="rounded-md border">
          <button
            type="button"
            onClick={() => setShowDropped((v) => !v)}
            className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium"
          >
            <span>Not this session ({state.dropped_tasks.length})</span>
            <ChevronDown
              className={cn("size-4 transition-transform", showDropped && "rotate-180")}
            />
          </button>
          {showDropped && (
            <ul className="divide-y border-t text-sm">
              {state.dropped_tasks.map((t) => (
                <li key={t.id} className="flex items-center gap-2 px-3 py-2">
                  {t.escalated && (
                    <Badge variant="destructive" className="shrink-0">overdue</Badge>
                  )}
                  <span className="font-medium">#{t.id} {t.action_type}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {t.drop_reason ?? "no time"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="space-y-2 border-t pt-4">
        <label className="text-sm font-medium" htmlFor="foreman-report">
          Tell the foreman what you finished
        </label>
        <Textarea
          id="foreman-report"
          rows={2}
          value={report}
          onChange={(e) => setReport(e.target.value)}
          placeholder="e.g. done with task 2 and the mulching (task 3)"
        />
        <div className="flex justify-end">
          <Button size="sm" onClick={sendReport} disabled={busy === "report" || !report.trim()}>
            {busy === "report" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Send className="size-3.5" />
            )}
            Report
          </Button>
        </div>
      </div>
    </div>
  );
}

function TaskRow({
  task,
  done,
  busy,
  onComplete,
}: {
  task: ScheduleTask;
  done: boolean;
  busy: boolean;
  onComplete: () => void;
}) {
  return (
    <li
      className={cn(
        "flex items-center gap-3 rounded-md border bg-card px-3 py-2.5 text-sm",
        done && "opacity-50",
      )}
    >
      {task.escalated && (
        <Badge variant="destructive" className="shrink-0">overdue</Badge>
      )}
      <div className="min-w-0">
        <p className={cn("truncate font-medium", done && "line-through")}>
          #{task.id} {task.action_type}
        </p>
        <p className="text-xs text-muted-foreground">
          tree #{task.tree_id} · ~{task.estimated_minutes ?? 30} min · priority{" "}
          {(task.effective_score ?? task.priority_score).toFixed(1)}
          {task.required_resources.length > 0 &&
            ` · ${task.required_resources.join(", ")}`}
        </p>
      </div>
      <Button
        size="sm"
        variant={done ? "ghost" : "outline"}
        className="ml-auto shrink-0"
        disabled={done || busy}
        onClick={onComplete}
      >
        {busy ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <Check className="size-3.5" />
        )}
        {done ? "Done" : "Mark Complete"}
      </Button>
    </li>
  );
}
