"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { ApiError, treesApi } from "@/lib/api";
import type { Tree, TreeInput } from "@/lib/types";

export interface ZoneOption {
  id: string;
  label: string;
}

interface TreeEntityFormProps {
  /** Rachio zones flattened to selectable options ("{device} · {zone}"). */
  zoneOptions: ZoneOption[];
  /** When provided the form edits this record; otherwise it creates a new one. */
  tree?: Tree | null;
  onSaved: (tree: Tree) => void;
  onCancel?: () => void;
}

type FieldName = keyof TreeInput;

const EMPTY: TreeInput = {
  species: "",
  variety: "",
  zone_id: null,
  planted_date: null,
  additional_context: null,
  notes: null,
  height_m: null,
  canopy_spread_m: null,
  estimated_gph: null,
  wetted_area_m2: null,
};

function fromTree(tree: Tree): TreeInput {
  return {
    species: tree.species,
    variety: tree.variety,
    zone_id: tree.zone_id,
    planted_date: tree.planted_date,
    additional_context: tree.additional_context,
    notes: tree.notes,
    height_m: tree.height_m,
    canopy_spread_m: tree.canopy_spread_m,
    estimated_gph: tree.estimated_gph,
    wetted_area_m2: tree.wetted_area_m2,
  };
}

export function TreeEntityForm({
  zoneOptions,
  tree,
  onSaved,
  onCancel,
}: TreeEntityFormProps) {
  const toast = useToast();
  const isEdit = Boolean(tree);

  const [values, setValues] = React.useState<TreeInput>(
    tree ? fromTree(tree) : EMPTY,
  );
  const [errors, setErrors] = React.useState<Partial<Record<FieldName, string>>>(
    {},
  );
  const [formError, setFormError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    setValues(tree ? fromTree(tree) : EMPTY);
    setErrors({});
    setFormError(null);
  }, [tree]);

  function set<K extends FieldName>(key: K, value: TreeInput[K]) {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  }

  function validate(): boolean {
    const next: Partial<Record<FieldName, string>> = {};
    if (!values.species.trim()) next.species = "Species is required.";
    if (!values.variety.trim()) next.variety = "Variety is required.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!validate()) return;

    const payload: TreeInput = {
      species: values.species.trim(),
      variety: values.variety.trim(),
      zone_id: values.zone_id ?? null,
      planted_date: values.planted_date || null,
      additional_context: values.additional_context?.trim() || null,
      notes: values.notes?.trim() || null,
      height_m: values.height_m ?? null,
      canopy_spread_m: values.canopy_spread_m ?? null,
      estimated_gph: values.estimated_gph ?? null,
      wetted_area_m2: values.wetted_area_m2 ?? null,
    };

    setSubmitting(true);
    try {
      const saved =
        isEdit && tree
          ? await treesApi.update(tree.tree_id, payload)
          : await treesApi.create(payload);
      toast.success(
        isEdit ? "Tree record updated" : "Tree record created",
        `${saved.species} · ${saved.variety} (#${saved.tree_id})`,
      );
      onSaved(saved);
      if (!isEdit) setValues(EMPTY);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.field && err.field in EMPTY) {
          setErrors((prev) => ({ ...prev, [err.field as FieldName]: err.detail }));
        }
        setFormError(err.detail);
        toast.error("Could not save tree record", err.detail);
      } else {
        setFormError("Unexpected error. Please retry.");
        toast.error("Could not save tree record");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Species"
          hint="Free text — e.g. mango, sapodilla, sugar apple"
          error={errors.species}
          htmlFor="tree-species"
        >
          <Input
            id="tree-species"
            value={values.species}
            onChange={(e) => set("species", e.target.value)}
            aria-invalid={Boolean(errors.species)}
            placeholder="mango"
            autoComplete="off"
          />
        </Field>

        <Field
          label="Variety"
          hint="Free text — e.g. Kent, Nam Doc Mai, Gefner"
          error={errors.variety}
          htmlFor="tree-variety"
        >
          <Input
            id="tree-variety"
            value={values.variety}
            onChange={(e) => set("variety", e.target.value)}
            aria-invalid={Boolean(errors.variety)}
            placeholder="Kent"
            autoComplete="off"
          />
        </Field>

        <Field label="Irrigation zone" error={errors.zone_id} htmlFor="tree-zone">
          <select
            id="tree-zone"
            value={values.zone_id ?? ""}
            onChange={(e) => set("zone_id", e.target.value || null)}
            className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">— none —</option>
            {zoneOptions.map((z) => (
              <option key={z.id} value={z.id}>
                {z.label}
              </option>
            ))}
            {/* keep an unknown/stale id selectable */}
            {values.zone_id &&
              !zoneOptions.some((z) => z.id === values.zone_id) && (
                <option value={values.zone_id}>{values.zone_id} (not in Rachio)</option>
              )}
          </select>
          <p className="mt-1 text-xs text-muted-foreground">
            Zones come from Rachio (read-only). Manage them in the Rachio app.
          </p>
        </Field>

        <Field
          label="Planted date"
          error={errors.planted_date}
          htmlFor="tree-planted"
        >
          <Input
            id="tree-planted"
            type="date"
            value={values.planted_date ?? ""}
            onChange={(e) => set("planted_date", e.target.value || null)}
          />
        </Field>

        <Field
          label="Canopy height (m)"
          hint="Scales Care Plan fertilizer / compost amounts and task time"
          error={errors.height_m}
          htmlFor="tree-height"
        >
          <Input
            id="tree-height"
            type="number"
            step="0.1"
            min="0"
            value={values.height_m ?? ""}
            onChange={(e) =>
              set("height_m", e.target.value ? Number(e.target.value) : null)
            }
            placeholder="e.g. 3.5"
          />
        </Field>

        <Field
          label="Canopy spread (m)"
          hint="Optional — defaults to 0.6 × height"
          error={errors.canopy_spread_m}
          htmlFor="tree-spread"
        >
          <Input
            id="tree-spread"
            type="number"
            step="0.1"
            min="0"
            value={values.canopy_spread_m ?? ""}
            onChange={(e) =>
              set(
                "canopy_spread_m",
                e.target.value ? Number(e.target.value) : null,
              )
            }
          />
        </Field>

        <Field
          label="Drip delivery (gal/hour)"
          hint="Whole-tree emitter output — drives the irrigation solver"
          error={errors.estimated_gph}
          htmlFor="tree-gph"
        >
          <Input
            id="tree-gph"
            type="number"
            step="0.5"
            min="0"
            value={values.estimated_gph ?? ""}
            onChange={(e) =>
              set("estimated_gph", e.target.value ? Number(e.target.value) : null)
            }
            placeholder="e.g. 8"
          />
        </Field>

        <Field
          label="Wetted area (m²)"
          hint="Soil area the emitters actually wet; blank ≈ 30% of canopy"
          error={errors.wetted_area_m2}
          htmlFor="tree-wetted"
        >
          <Input
            id="tree-wetted"
            type="number"
            step="0.1"
            min="0"
            value={values.wetted_area_m2 ?? ""}
            onChange={(e) =>
              set("wetted_area_m2", e.target.value ? Number(e.target.value) : null)
            }
            placeholder="e.g. 1.5"
          />
        </Field>
      </div>

      <Field
        label="Additional context"
        hint="RAG-sourced free-text tier; leave blank until resolved"
        error={errors.additional_context}
        htmlFor="tree-context"
      >
        <Textarea
          id="tree-context"
          value={values.additional_context ?? ""}
          onChange={(e) => set("additional_context", e.target.value || null)}
          placeholder="Rootstock notes, canopy training history, pest pressure…"
        />
      </Field>

      <Field label="Notes" error={errors.notes} htmlFor="tree-notes">
        <Textarea
          id="tree-notes"
          value={values.notes ?? ""}
          onChange={(e) => set("notes", e.target.value || null)}
        />
      </Field>

      {isEdit && tree && (
        <p className="border-t pt-4 text-sm text-muted-foreground">
          Manage &amp; rank linked knowledge sources on the{" "}
          <Link
            href={`/trees/${tree.tree_id}`}
            className="font-medium text-primary hover:underline"
          >
            tree page
          </Link>
          .
        </p>
      )}

      {formError && (
        <p
          role="alert"
          className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
        >
          {formError}
        </p>
      )}

      <div className="flex items-center justify-end gap-2">
        {onCancel && (
          <Button
            type="button"
            variant="ghost"
            onClick={onCancel}
            disabled={submitting}
          >
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={submitting}>
          {submitting && <Loader2 className="animate-spin" />}
          {isEdit ? "Save changes" : "Create tree"}
        </Button>
      </div>
    </form>
  );
}

function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}
