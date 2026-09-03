"use client";

import * as React from "react";
import {
  CalendarClock,
  Loader2,
  Sparkles,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { ApiError, carePlanApi, treesApi } from "@/lib/api";
import type { CarePlan, RateClass, TaskTemplate, Tree, TreePhenology } from "@/lib/types";
import { BaselineWizard } from "./baseline-wizard";
import { MonthStrip, constraintCaption } from "./month-strip";
import {
  MonthMultiSelect,
  phenologyListsFromTree,
  phenologyListsFromRead,
} from "./month-multi-select";

const RATE_CLASSES: RateClass[] = ["light", "standard", "heavy"];

export function CarePlanTab({
  treeId,
  autoGenerate = false,
}: {
  treeId: number;
  autoGenerate?: boolean;
}) {
  const toast = useToast();
  const [plan, setPlan] = React.useState<CarePlan | null>(null);
  const [tree, setTree] = React.useState<Tree | null>(null);
  const [generating, setGenerating] = React.useState(false);
  const [wizardOpen, setWizardOpen] = React.useState(false);
  const didAuto = React.useRef(false);

  const load = React.useCallback(async () => {
    const [p, t] = await Promise.all([
      carePlanApi.get(treeId),
      treesApi.get(treeId),
    ]);
    setPlan(p);
    setTree(t);
    return p;
  }, [treeId]);

  const generate = React.useCallback(async () => {
    setGenerating(true);
    try {
      setPlan(await carePlanApi.generate(treeId));
      toast.success("Care plan generated", "Review and adjust the tasks below.");
    } catch (err) {
      toast.error(
        "Could not generate the care plan",
        err instanceof ApiError
          ? err.status === 503
            ? "The local model (Ollama) is unavailable."
            : err.detail
          : undefined,
      );
    } finally {
      setGenerating(false);
    }
  }, [treeId, toast]);

  React.useEffect(() => {
    load().then((p) => {
      if (autoGenerate && !p.generated && !didAuto.current) {
        didAuto.current = true;
        void generate();
      }
    });
  }, [load, generate, autoGenerate]);

  if (!plan || !tree) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-2">
        <TreeDimensions
          tree={tree}
          onSaved={(t) => {
            setTree(t);
            toast.success(
              "Dimensions updated",
              "Regenerate the plan to rescale amounts.",
            );
          }}
        />
        <BiologicalCalendar
          tree={tree}
          onSaved={async (t) => {
            setTree(t);
            const p = await carePlanApi.get(treeId);
            setPlan(p);
            toast.success(
              "Biological calendar updated",
              "Month strips reflect the new flowering / harvest / dormancy dates.",
            );
          }}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Care Plan</h2>
          <p className="text-sm text-muted-foreground">
            {plan.generated
              ? `${plan.templates.length} recurring tasks · ${plan.pending_task_count} scheduled`
              : "The Agronomist drafts routine tasks from this tree's linked notes and size."}
          </p>
        </div>
        <div className="flex gap-2">
          {plan.generated && (
            <Button
              variant="outline"
              onClick={() => setWizardOpen(true)}
              className="gap-1.5"
            >
              <CalendarClock className="size-4" />
              {plan.pending_task_count > 0 ? "Adjust dates" : "Set up schedule"}
            </Button>
          )}
          <Button
            onClick={generate}
            disabled={generating}
            className="gap-1.5"
          >
            {generating ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Generating care plan…
              </>
            ) : (
              <>
                <Sparkles className="size-4" />
                {plan.generated ? "Regenerate" : "Generate Care Plan"}
              </>
            )}
          </Button>
        </div>
      </div>

      {generating && !plan.generated ? (
        <div className="rounded-lg border border-dashed py-16 text-center text-sm text-muted-foreground">
          <Loader2 className="mx-auto mb-2 size-5 animate-spin" />
          Asking the Agronomist for a routine care schedule…
        </div>
      ) : plan.templates.length === 0 ? (
        <div className="rounded-lg border border-dashed py-16 text-center text-sm text-muted-foreground">
          No care plan yet.
        </div>
      ) : (
        <ul className="space-y-3">
          {plan.templates.map((t) => (
            <TemplateRow
              key={t.id}
              template={t}
              phenology={plan.phenology}
              onChanged={(next) =>
                setPlan((p) =>
                  p
                    ? {
                        ...p,
                        templates: p.templates.map((x) =>
                          x.id === next.id ? next : x,
                        ),
                      }
                    : p,
                )
              }
              onDeleted={() => load()}
            />
          ))}
        </ul>
      )}

      {plan.pending_task_count > 0 && (
        <p className="text-sm text-muted-foreground">
          Scheduled tasks appear in the{" "}
          <Link href="/schedule" className="font-medium text-primary hover:underline">
            schedule inbox
          </Link>
          .
        </p>
      )}

      <BaselineWizard
        treeId={treeId}
        questions={plan.baseline_questions}
        phenology={plan.phenology}
        templates={plan.templates}
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        onScheduled={() => load()}
      />
    </div>
  );
}

// --------------------------------------------------------------------------

function TreeDimensions({
  tree,
  onSaved,
}: {
  tree: Tree;
  onSaved: (t: Tree) => void;
}) {
  const toast = useToast();
  const [height, setHeight] = React.useState(tree.height_m?.toString() ?? "");
  const [spread, setSpread] = React.useState(
    tree.canopy_spread_m?.toString() ?? "",
  );
  const [saving, setSaving] = React.useState(false);
  const dirty =
    height !== (tree.height_m?.toString() ?? "") ||
    spread !== (tree.canopy_spread_m?.toString() ?? "");

  async function save() {
    setSaving(true);
    try {
      onSaved(
        await treesApi.update(tree.tree_id, {
          height_m: height ? Number(height) : null,
          canopy_spread_m: spread ? Number(spread) : null,
        }),
      );
    } catch (err) {
      toast.error(
        "Could not save dimensions",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-4 rounded-lg border bg-muted/20 p-3">
      <div className="space-y-1">
        <Label htmlFor="tree-height" className="text-xs">
          Canopy height (m)
        </Label>
        <Input
          id="tree-height"
          type="number"
          step="0.1"
          min="0"
          className="h-8 w-28"
          value={height}
          onChange={(e) => setHeight(e.target.value)}
          placeholder="e.g. 3.5"
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="tree-spread" className="text-xs">
          Canopy spread (m)
        </Label>
        <Input
          id="tree-spread"
          type="number"
          step="0.1"
          min="0"
          className="h-8 w-28"
          value={spread}
          onChange={(e) => setSpread(e.target.value)}
          placeholder="optional"
        />
      </div>
      <p className="flex-1 text-xs text-muted-foreground">
        Used to scale fertilizer / compost volumes and task time. Spread
        defaults to 0.6 × height when blank.
      </p>
      {dirty && (
        <Button size="sm" onClick={save} disabled={saving}>
          {saving && <Loader2 className="size-3.5 animate-spin" />}
          Save
        </Button>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------

function BiologicalCalendar({
  tree,
  onSaved,
}: {
  tree: Tree;
  onSaved: (t: Tree) => void | Promise<void>;
}) {
  const toast = useToast();
  const initial = phenologyListsFromTree(tree);
  const [flowering, setFlowering] = React.useState<number[]>(initial.flowering);
  const [harvest, setHarvest] = React.useState<number[]>(initial.harvest);
  const [dormancy, setDormancy] = React.useState<number[]>(initial.dormancy);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    const next = phenologyListsFromTree(tree);
    setFlowering(next.flowering);
    setHarvest(next.harvest);
    setDormancy(next.dormancy);
  }, [tree]);

  const dirty =
    JSON.stringify(flowering) !== JSON.stringify(initial.flowering) ||
    JSON.stringify(harvest) !== JSON.stringify(initial.harvest) ||
    JSON.stringify(dormancy) !== JSON.stringify(initial.dormancy);

  async function save() {
    setSaving(true);
    try {
      await onSaved(
        await treesApi.update(tree.tree_id, {
          expected_flowering_months: flowering,
          expected_harvest_months: harvest,
          expected_dormancy_months: dormancy,
          expected_flowering_month: flowering[0] ?? null,
          expected_harvest_month: harvest[0] ?? null,
          expected_dormancy_month: dormancy[0] ?? null,
        }),
      );
    } catch (err) {
      toast.error(
        "Could not save biological calendar",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
      <div>
        <h3 className="text-sm font-semibold">Biological calendar</h3>
        <p className="text-xs text-muted-foreground">
          Some plants flower twice a year — select every month this tree
          typically does.
        </p>
      </div>
      <MonthMultiSelect
        label="Flower"
        selected={flowering}
        onChange={setFlowering}
      />
      <MonthMultiSelect
        label="Harvest"
        selected={harvest}
        onChange={setHarvest}
      />
      <MonthMultiSelect
        label="Dormancy"
        selected={dormancy}
        onChange={setDormancy}
      />
      {dirty && (
        <div className="flex justify-end">
          <Button size="sm" onClick={save} disabled={saving}>
            {saving && <Loader2 className="size-3.5 animate-spin" />}
            Save
          </Button>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------

function TemplateRow({
  template,
  phenology,
  onChanged,
  onDeleted,
}: {
  template: TaskTemplate;
  phenology: TreePhenology;
  onChanged: (t: TaskTemplate) => void;
  onDeleted: () => void;
}) {
  const toast = useToast();
  const [draft, setDraft] = React.useState({
    name: template.name,
    interval_days: String(template.interval_days),
    estimated_minutes: String(template.estimated_minutes),
    priority_score: String(template.priority_score),
    rate_class: template.rate_class,
    required_resources: template.required_resources.join(", "),
  });
  const [busy, setBusy] = React.useState(false);

  const dirty =
    draft.name !== template.name ||
    draft.interval_days !== String(template.interval_days) ||
    draft.estimated_minutes !== String(template.estimated_minutes) ||
    draft.priority_score !== String(template.priority_score) ||
    draft.rate_class !== template.rate_class ||
    draft.required_resources !== template.required_resources.join(", ");

  async function save() {
    setBusy(true);
    try {
      const updated = await carePlanApi.updateTemplate(template.id, {
        name: draft.name.trim(),
        interval_days: Number(draft.interval_days),
        estimated_minutes: Number(draft.estimated_minutes),
        priority_score: Number(draft.priority_score),
        rate_class: draft.rate_class,
        required_resources: draft.required_resources
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      onChanged(updated);
      setDraft((d) => ({
        ...d,
        estimated_minutes: String(updated.estimated_minutes),
        required_resources: updated.required_resources.join(", "),
      }));
      toast.success("Task updated");
    } catch (err) {
      toast.error(
        "Could not update task",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await carePlanApi.deleteTemplate(template.id);
      onDeleted();
    } catch (err) {
      toast.error(
        "Could not remove task",
        err instanceof ApiError ? err.detail : undefined,
      );
      setBusy(false);
    }
  }

  const anchorMonths =
    template.biological_anchor === "flowering"
      ? phenologyListsFromRead(phenology).flowering
      : template.biological_anchor === "harvest"
        ? phenologyListsFromRead(phenology).harvest
        : template.biological_anchor === "dormancy"
          ? phenologyListsFromRead(phenology).dormancy
          : [];
  const caption = constraintCaption(template);

  return (
    <li className="rounded-lg border p-3">
      <div className="flex items-start gap-3">
        <span className="mt-1 rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium uppercase text-muted-foreground">
          {template.category}
        </span>
        <div className="grid flex-1 gap-3 sm:grid-cols-2">
          <LabeledInput label="Name">
            <Input
              className="h-8"
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
            />
          </LabeledInput>
          <LabeledInput label="Rate class">
            <select
              className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm"
              value={draft.rate_class}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  rate_class: e.target.value as RateClass,
                }))
              }
            >
              {RATE_CLASSES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </LabeledInput>
          <LabeledInput label="Every (days)">
            <Input
              className="h-8"
              type="number"
              min="1"
              value={draft.interval_days}
              onChange={(e) =>
                setDraft((d) => ({ ...d, interval_days: e.target.value }))
              }
            />
          </LabeledInput>
          <LabeledInput label="Est. minutes">
            <Input
              className="h-8"
              type="number"
              min="1"
              value={draft.estimated_minutes}
              onChange={(e) =>
                setDraft((d) => ({ ...d, estimated_minutes: e.target.value }))
              }
            />
          </LabeledInput>
          <LabeledInput label="Priority (0–10)">
            <Input
              className="h-8"
              type="number"
              min="0"
              max="10"
              step="0.5"
              value={draft.priority_score}
              onChange={(e) =>
                setDraft((d) => ({ ...d, priority_score: e.target.value }))
              }
            />
          </LabeledInput>
          <LabeledInput label="Resources (comma-separated)">
            <Input
              className="h-8"
              value={draft.required_resources}
              onChange={(e) =>
                setDraft((d) => ({
                  ...d,
                  required_resources: e.target.value,
                }))
              }
            />
          </LabeledInput>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="text-muted-foreground hover:text-destructive"
          aria-label="Remove task"
          disabled={busy}
          onClick={remove}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>

      {(template.valid_months.length > 0 || template.biological_anchor) && (
        <div className="mt-2 space-y-1 pl-1">
          <MonthStrip
            validMonths={template.valid_months}
            anchorMonths={anchorMonths}
            anchorOffsetDays={template.anchor_offset_days}
          />
          {caption && (
            <p className="text-[11px] text-muted-foreground">{caption}</p>
          )}
        </div>
      )}

      {template.resource_plan.length > 0 && (
        <p className="mt-2 pl-1 text-xs text-muted-foreground">
          Computed for this tree:{" "}
          {template.resource_plan
            .map((r) => `${r.quantity} ${r.unit} ${r.name}`)
            .join(" · ")}
        </p>
      )}
      {template.baseline_question && (
        <p className="mt-1 pl-1 text-xs italic text-muted-foreground">
          Asks: “{template.baseline_question}”
        </p>
      )}

      {dirty && (
        <div className="mt-2 flex justify-end">
          <Button size="sm" onClick={save} disabled={busy}>
            {busy && <Loader2 className="size-3.5 animate-spin" />}
            Save changes
          </Button>
        </div>
      )}
    </li>
  );
}

function LabeledInput({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="space-y-1 text-xs text-muted-foreground">
      <span>{label}</span>
      {children}
    </label>
  );
}
