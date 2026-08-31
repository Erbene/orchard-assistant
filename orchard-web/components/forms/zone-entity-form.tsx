"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { ApiError, zonesApi } from "@/lib/api";
import type { Zone } from "@/lib/types";

interface ZoneEntityFormProps {
  zone?: Zone | null;
  onSaved: (zone: Zone) => void;
  onCancel?: () => void;
}

export function ZoneEntityForm({ zone, onSaved, onCancel }: ZoneEntityFormProps) {
  const toast = useToast();
  const isEdit = Boolean(zone);

  const [name, setName] = React.useState(zone?.name ?? "");
  const [soil, setSoil] = React.useState(zone?.soil_drainage ?? "");
  const [waterSource, setWaterSource] = React.useState(zone?.water_source ?? "");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [formError, setFormError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    setName(zone?.name ?? "");
    setSoil(zone?.soil_drainage ?? "");
    setWaterSource(zone?.water_source ?? "");
    setErrors({});
    setFormError(null);
  }, [zone]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setErrors({ name: "Name is required." });
      return;
    }
    setErrors({});
    setSubmitting(true);
    setFormError(null);
    try {
      const body = {
        name: name.trim(),
        soil_drainage: soil.trim() || null,
        water_source: waterSource.trim() || null,
      };
      const saved =
        isEdit && zone
          ? await zonesApi.update(zone.zone_id, body)
          : await zonesApi.create(body);
      toast.success(
        isEdit ? "Zone updated" : "Zone created",
        `${saved.name} (#${saved.zone_id})`,
      );
      onSaved(saved);
      if (!isEdit) {
        setName("");
        setSoil("");
        setWaterSource("");
      }
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.field) setErrors({ [err.field]: err.detail });
        setFormError(err.detail);
        toast.error("Could not save zone", err.detail);
      } else {
        setFormError("Unexpected error. Please retry.");
        toast.error("Could not save zone");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="zone-name">Name</Label>
          <Input
            id="zone-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={Boolean(errors.name)}
            placeholder="North block"
          />
          {errors.name ? (
            <p className="text-xs text-destructive">{errors.name}</p>
          ) : (
            <p className="text-xs text-muted-foreground">
              {isEdit
                ? `Zone id #${zone?.zone_id} (auto-assigned)`
                : "Zone id is assigned automatically on save."}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="zone-soil">Soil drainage</Label>
          <Input
            id="zone-soil"
            value={soil}
            onChange={(e) => setSoil(e.target.value)}
            aria-invalid={Boolean(errors.soil_drainage)}
            placeholder="fast, heavy clay, sandy loam…"
            autoComplete="off"
          />
          {errors.soil_drainage && (
            <p className="text-xs text-destructive">{errors.soil_drainage}</p>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="zone-water-source">Water Source</Label>
        <Input
          id="zone-water-source"
          value={waterSource}
          onChange={(e) => setWaterSource(e.target.value)}
          aria-invalid={Boolean(errors.water_source)}
          placeholder="well, canal, municipal, rainwater catchment…"
          autoComplete="off"
        />
        {errors.water_source ? (
          <p className="text-xs text-destructive">{errors.water_source}</p>
        ) : (
          <p className="text-xs text-muted-foreground">
            Free text — irrigation water source for this zone. Stored exactly as
            typed.
          </p>
        )}
      </div>

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
          {isEdit ? "Save changes" : "Create zone"}
        </Button>
      </div>
    </form>
  );
}
