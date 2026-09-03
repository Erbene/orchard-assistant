"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { ApiError, irrigationApi } from "@/lib/api";
import type { SupervisorConfig, ZoneConfig } from "@/lib/types";

export function ScheduleConfig({
  zones,
  supervisor,
  onChange,
}: {
  zones: ZoneConfig[];
  supervisor: SupervisorConfig;
  onChange: () => void;
}) {
  const toast = useToast();

  async function saveSupervisor(patch: Partial<SupervisorConfig>) {
    try {
      await irrigationApi.updateSupervisor(patch);
      onChange();
    } catch (err) {
      toast.error(
        "Could not save supervisor settings",
        err instanceof ApiError ? err.detail : undefined,
      );
    }
  }

  return (
    <div className="space-y-5">
      <section className="rounded-lg border p-4">
        <h2 className="text-sm font-semibold">Supervisor</h2>
        <div className="mt-3 flex flex-wrap items-end gap-6">
          <div className="space-y-1">
            <Label htmlFor="freq" className="text-xs">
              Run frequency (hours)
            </Label>
            <Input
              id="freq"
              type="number"
              min={1}
              max={168}
              defaultValue={supervisor.supervisor_frequency_hours}
              className="h-8 w-28"
              onBlur={(e) => {
                const v = Number(e.target.value);
                if (v && v !== supervisor.supervisor_frequency_hours)
                  void saveSupervisor({ supervisor_frequency_hours: v });
              }}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={supervisor.auto_approve_skips}
              onChange={(e) =>
                void saveSupervisor({ auto_approve_skips: e.target.checked })
              }
            />
            Auto-approve schedule skips (they only save water)
          </label>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          The supervisor ticks in-process on this cadence while the API is up (no
          external cron). <strong>Run Supervision Task</strong> still runs
          immediately. Per-zone watering interval is not configured here — it is
          inferred from Rachio last watering; a 2-day gap is enforced in code.
          Watering proposals (pass, duration change, emergency) need grower
          approval; schedule skips can auto-approve when the checkbox above is
          on.
        </p>
      </section>

      <section className="rounded-lg border">
        <h2 className="border-b px-4 py-3 text-sm font-semibold">
          Baseline schedule per zone
        </h2>
        {zones.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            No irrigation zones yet — set a Rachio zone on a tree first.
          </p>
        ) : (
          <ul className="divide-y">
            {zones.map((z) => (
              <ZoneRow key={z.zone_id} zone={z} onSaved={onChange} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ZoneRow({ zone, onSaved }: { zone: ZoneConfig; onSaved: () => void }) {
  const toast = useToast();
  const [minutes, setMinutes] = React.useState(String(zone.baseline_minutes));
  const [saving, setSaving] = React.useState(false);
  const dirty = minutes !== String(zone.baseline_minutes);

  async function save(patch: Parameters<typeof irrigationApi.updateZone>[1]) {
    setSaving(true);
    try {
      await irrigationApi.updateZone(zone.zone_id, patch);
      onSaved();
    } catch (err) {
      toast.error(
        "Could not save zone",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <li className="flex flex-wrap items-end gap-4 px-4 py-3">
      <div className="min-w-32">
        <p className="text-sm font-medium">Zone {zone.zone_id}</p>
        <p className="text-xs text-muted-foreground">
          {zone.tree_count} tree{zone.tree_count === 1 ? "" : "s"}
        </p>
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Run (min)</Label>
        <Input
          type="number"
          min={0}
          max={180}
          value={minutes}
          onChange={(e) => setMinutes(e.target.value)}
          className="h-8 w-24"
        />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={zone.supervised}
          onChange={(e) => void save({ supervised: e.target.checked })}
        />
        Supervised
      </label>
      {dirty && (
        <Button
          size="sm"
          disabled={saving}
          onClick={() =>
            void save({
              baseline_minutes: Number(minutes),
            })
          }
        >
          {saving && <Loader2 className="size-3.5 animate-spin" />}
          Save
        </Button>
      )}
    </li>
  );
}
