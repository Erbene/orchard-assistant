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
import type { BaselineQuestion } from "@/lib/types";

interface Props {
  treeId: number;
  questions: BaselineQuestion[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Fired after the first recurring tasks are created. */
  onScheduled: () => void;
}

type Answer = { date: string; unknown: boolean };

/**
 * Dynamic form built from the Agronomist's baseline questions. For each task
 * that needs a "when was this last done?" the grower gives a date (or ticks
 * "not sure"); the backend turns those into the first `scheduled_date` for
 * every template and materialises the recurring tasks.
 */
export function BaselineWizard({
  treeId,
  questions,
  open,
  onOpenChange,
  onScheduled,
}: Props) {
  const toast = useToast();
  const [answers, setAnswers] = React.useState<Record<number, Answer>>({});
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    if (open) setAnswers({});
  }, [open]);

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
      const tasks = await carePlanApi.baseline(treeId, payload);
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
