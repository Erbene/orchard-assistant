"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { ApiError, carePlanApi } from "@/lib/api";
import type { BaselineQuestion, TaskTemplate, TreePhenology } from "@/lib/types";
import {
  MonthMultiSelect,
  phenologyListsFromRead,
} from "./month-multi-select";

interface Props {
  treeId: number;
  questions: BaselineQuestion[];
  phenology: TreePhenology;
  templates: TaskTemplate[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Fired after the first recurring tasks are created. */
  onScheduled: () => void;
}

type Answer = { date: string; unknown: boolean };

type MonthState = {
  flowering: number[];
  harvest: number[];
  dormancy: number[];
};

/**
 * Dynamic form built from the Agronomist's baseline questions. For each task
 * that needs a "when was this last done?" the grower gives a date (or ticks
 * "not sure"); the backend turns those into the first `scheduled_date` for
 * every template and materialises the recurring tasks.
 */
export function BaselineWizard({
  treeId,
  questions,
  phenology,
  templates,
  open,
  onOpenChange,
  onScheduled,
}: Props) {
  const toast = useToast();
  const [answers, setAnswers] = React.useState<Record<number, Answer>>({});
  const [months, setMonths] = React.useState<MonthState>(() =>
    phenologyListsFromRead(phenology),
  );
  const [submitting, setSubmitting] = React.useState(false);

  const hasBiologicalTemplates = templates.some((t) => t.biological_anchor);

  React.useEffect(() => {
    if (open) {
      setAnswers({});
      setMonths(phenologyListsFromRead(phenology));
    }
  }, [open, phenology]);

  const set = (id: number, patch: Partial<Answer>) =>
    setAnswers((a) => {
      const prev = a[id] ?? { date: "", unknown: false };
      return { ...a, [id]: { ...prev, ...patch } };
    });

  async function submit() {
    setSubmitting(true);
    try {
      const payload = questions.map((q) => {
        const a = answers[q.template_id];
        return {
          template_id: q.template_id,
          last_done: a && !a.unknown && a.date ? a.date : null,
        };
      });
      const phenologyPayload = hasBiologicalTemplates
        ? {
            flowering_months: months.flowering,
            harvest_months: months.harvest,
            dormancy_months: months.dormancy,
            flowering_month: months.flowering[0] ?? null,
            harvest_month: months.harvest[0] ?? null,
            dormancy_month: months.dormancy[0] ?? null,
          }
        : undefined;
      const tasks = await carePlanApi.baseline(treeId, payload, phenologyPayload);
      toast.success(
        "Schedule ready",
        `${tasks.length} recurring task${tasks.length === 1 ? "" : "s"} created.`,
      );
      onOpenChange(false);
      onScheduled();
    } catch (err) {
      toast.error(
        "Could not create the schedule",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Set first due dates</DialogTitle>
          <DialogDescription>
            Tell us when each job was last done. We&rsquo;ll schedule the next
            one from there. Leave a date blank or tick &ldquo;not sure&rdquo; to
            start counting from today.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[55vh] space-y-4 overflow-y-auto py-1">
          {hasBiologicalTemplates && (
            <div className="space-y-3 rounded-md border bg-muted/20 p-3">
              <p className="text-sm font-medium">When does this tree typically…</p>
              <p className="text-xs text-muted-foreground">
                Some plants flower twice a year — select every month this tree
                typically does. Confirm or adjust the Agronomist&rsquo;s defaults.
              </p>
              <MonthMultiSelect
                label="Flower"
                selected={months.flowering}
                onChange={(flowering) =>
                  setMonths((m) => ({ ...m, flowering }))
                }
              />
              <MonthMultiSelect
                label="Harvest"
                selected={months.harvest}
                onChange={(harvest) => setMonths((m) => ({ ...m, harvest }))}
              />
              <MonthMultiSelect
                label="Dormancy"
                selected={months.dormancy}
                onChange={(dormancy) => setMonths((m) => ({ ...m, dormancy }))}
              />
            </div>
          )}

          {questions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              This plan has no date-dependent tasks — everything will be
              scheduled from today.
            </p>
          ) : (
            questions.map((q) => {
              const a = answers[q.template_id] ?? { date: "", unknown: false };
              return (
                <div key={q.template_id} className="space-y-1.5">
                  <Label htmlFor={`bl-${q.template_id}`}>
                    {q.name}
                    <span className="ml-1 font-normal text-muted-foreground">
                      · {q.question}
                    </span>
                  </Label>
                  <div className="flex items-center gap-3">
                    <Input
                      id={`bl-${q.template_id}`}
                      type="date"
                      className="max-w-44"
                      value={a.date}
                      disabled={a.unknown}
                      onChange={(e) =>
                        set(q.template_id, { date: e.target.value })
                      }
                    />
                    <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={a.unknown}
                        onChange={(e) =>
                          set(q.template_id, { unknown: e.target.checked })
                        }
                      />
                      Not sure
                    </label>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button onClick={submit} disabled={submitting}>
            {submitting && <Loader2 className="size-4 animate-spin" />}
            Create schedule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
