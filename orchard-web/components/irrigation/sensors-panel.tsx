"use client";

import * as React from "react";
import { CloudRain, Loader2, RotateCcw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { ApiError, irrigationApi } from "@/lib/api";
import type { SensorOverridesIn, SensorSnapshot, SensorTreeRead } from "@/lib/types";
import { zoneDisplayName } from "@/lib/zone-label";
import { cn } from "@/lib/utils";

function fmt(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

function vwcTone(current: number | null, target: number): "dry" | "ok" | "wet" | "none" {
  if (current == null) return "none";
  if (current < target - 4) return "dry";
  if (current > target + 4) return "wet";
  return "ok";
}

export function SensorsPanel({
  demoEnabled,
  reloadToken = 0,
}: {
  demoEnabled: boolean;
  reloadToken?: number;
}) {
  const toast = useToast();
  const [snap, setSnap] = React.useState<SensorSnapshot | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [rain, setRain] = React.useState("");
  const [qpf, setQpf] = React.useState("");
  const [forDate, setForDate] = React.useState("");

  const load = React.useCallback(async () => {
    const next = await irrigationApi.sensors();
    setSnap(next);
    setRain(String(next.rain_24h_mm));
    setQpf(String(next.forecast_rain_24h_mm));
    setForDate(next.for_date);
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void load()
      .catch((err) => {
        if (!cancelled) {
          toast.error(
            "Could not load sensors",
            err instanceof ApiError ? err.detail : undefined,
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load, reloadToken]);

  async function apply(patch: SensorOverridesIn, ok = "Pins updated") {
    setSaving(true);
    try {
      const next = await irrigationApi.applySensorOverrides(patch);
      setSnap(next);
      setRain(String(next.rain_24h_mm));
      setQpf(String(next.forecast_rain_24h_mm));
      setForDate(next.for_date);
      toast.success(ok);
    } catch (err) {
      toast.error(
        "Could not update pins",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  async function saveWeather() {
    const rainN = Number(rain);
    const qpfN = Number(qpf);
    if (!Number.isFinite(rainN) || !Number.isFinite(qpfN) || !forDate) {
      toast.error("Enter rain, forecast, and a date");
      return;
    }
    await apply({
      rain_24h_mm: rainN,
      forecast_rain_24h_mm: qpfN,
      for_date: forDate,
    });
  }

  async function resetPins() {
    setSaving(true);
    try {
      const next = await irrigationApi.resetDemo();
      setSnap(next);
      setRain(String(next.rain_24h_mm));
      setQpf(String(next.forecast_rain_24h_mm));
      setForDate(next.for_date);
      toast.success("Demo pins cleared");
    } catch (err) {
      toast.error(
        "Could not reset pins",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading && !snap) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!snap) return null;

  return (
    <div className="space-y-5">
      <section className="rounded-lg border p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <CloudRain className="size-4 text-primary" />
              Orchard inputs
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              These are the values the supervisor uses for water balance and the
              2-day spacing guard.
              {demoEnabled
                ? " Demo mode is on — edit the fields, then run supervision."
                : " Live mode is read-only (NWS forecast, Rachio last-watered, stub moisture until hardware is wired)."}
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {snap.active_scenario_id && (
              <Badge>Scenario: {snap.active_scenario_id}</Badge>
            )}
            {snap.pins_active && !snap.active_scenario_id && (
              <Badge variant="secondary">Custom pins</Badge>
            )}
            <Badge variant={snap.rain_overridden ? "default" : "muted"}>
              Rain {snap.rain_source}
            </Badge>
            <Badge variant={snap.forecast_overridden ? "default" : "muted"}>
              QPF {snap.forecast_source}
            </Badge>
          </div>
        </div>

        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <Field
            id="for-date"
            label="For date"
            hint="Phenology + which forecast day is scored"
          >
            {demoEnabled ? (
              <Input
                id="for-date"
                type="date"
                value={forDate}
                onChange={(e) => setForDate(e.target.value)}
              />
            ) : (
              <ReadOnlyValue>{forDate || "—"}</ReadOnlyValue>
            )}
          </Field>
          <Field
            id="rain-24h"
            label="Rain last 24h (mm)"
            hint={snap.rain_overridden ? "Pinned gauge" : "Gauge stub"}
          >
            {demoEnabled ? (
              <Input
                id="rain-24h"
                type="number"
                min={0}
                max={500}
                step={0.1}
                value={rain}
                onChange={(e) => setRain(e.target.value)}
              />
            ) : (
              <ReadOnlyValue>{fmt(Number(rain))}</ReadOnlyValue>
            )}
          </Field>
          <Field
            id="qpf-24h"
            label="Forecast next 24h (mm)"
            hint={
              snap.forecast_available
                ? snap.forecast_overridden
                  ? "Pinned QPF"
                  : "NWS quantitative precip"
                : snap.forecast_error || "Forecast unavailable"
            }
          >
            {demoEnabled ? (
              <Input
                id="qpf-24h"
                type="number"
                min={0}
                max={500}
                step={0.1}
                value={qpf}
                onChange={(e) => setQpf(e.target.value)}
              />
            ) : (
              <ReadOnlyValue>{fmt(Number(qpf))}</ReadOnlyValue>
            )}
          </Field>
        </div>

        {demoEnabled && (
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" disabled={saving} onClick={() => void saveWeather()}>
              {saving ? <Loader2 className="size-3.5 animate-spin" /> : null}
              Apply weather pins
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={saving || !snap.pins_active}
              onClick={() => void resetPins()}
            >
              <RotateCcw className="size-3.5" />
              Reset all pins
            </Button>
          </div>
        )}
      </section>

      {snap.zones.length === 0 ? (
        <div className="rounded-lg border border-dashed py-16 text-center text-sm text-muted-foreground">
          Assign trees to a Rachio zone to see moisture, deficit, and last-watered.
        </div>
      ) : (
        snap.zones.map((zone) => (
          <section key={zone.zone_id} className="overflow-hidden rounded-lg border">
            <header className="flex flex-wrap items-center gap-3 border-b bg-muted/30 px-4 py-3">
              <h3 className="font-medium">
                {zoneDisplayName(zone) ?? `Zone ${zone.zone_id}`}
              </h3>
              <Badge variant="outline">Deficit {fmt(zone.deficit_score)}</Badge>
              <Badge variant="muted">{zone.baseline_minutes} min baseline</Badge>
              <div className="ml-auto flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Last watered</span>
                {demoEnabled ? (
                  <Input
                    id={`lw-${zone.zone_id}`}
                    type="date"
                    className="h-8 w-[11.5rem]"
                    value={zone.last_watered_date ?? ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      void apply(
                        {
                          last_watered: [
                            { zone_id: zone.zone_id, last_watered_date: v || null },
                          ],
                        },
                        "Last-watered pin updated",
                      );
                    }}
                  />
                ) : (
                  <ReadOnlyValue>{zone.last_watered_date ?? "—"}</ReadOnlyValue>
                )}
                <Badge variant="muted">{zone.last_watered_source}</Badge>
              </div>
            </header>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-medium">Tree</th>
                    <th className="px-3 py-2 font-medium">Stage</th>
                    <th className="px-3 py-2 font-medium">VWC %</th>
                    <th className="px-3 py-2 font-medium">Target</th>
                    <th className="px-3 py-2 font-medium">Gap</th>
                    <th className="px-3 py-2 font-medium">Deficit</th>
                    <th className="px-3 py-2 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {zone.trees.map((tree) => (
                    <TreeRow
                      key={tree.tree_id}
                      tree={tree}
                      demoEnabled={demoEnabled}
                      disabled={saving}
                      onVwc={(vwc) =>
                        void apply(
                          { moisture: [{ tree_id: tree.tree_id, vwc_pct: vwc }] },
                          `${tree.species} moisture pinned`,
                        )
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function ReadOnlyValue({ children }: { children: React.ReactNode }) {
  return <p className="text-sm font-medium">{children}</p>;
}

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs">
        {label}
      </Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

function TreeRow({
  tree,
  demoEnabled,
  disabled,
  onVwc,
}: {
  tree: SensorTreeRead;
  demoEnabled: boolean;
  disabled: boolean;
  onVwc: (vwc: number) => void;
}) {
  const [value, setValue] = React.useState(
    tree.current_vwc == null ? "" : String(tree.current_vwc),
  );
  React.useEffect(() => {
    setValue(tree.current_vwc == null ? "" : String(tree.current_vwc));
  }, [tree.current_vwc]);

  const tone = vwcTone(tree.current_vwc, tree.target_vwc);
  const source =
    tree.sensors[0]?.source ??
    (tree.moisture_resolved_via === "none" ? "none" : tree.moisture_resolved_via);

  return (
    <tr className="border-b last:border-0">
      <td className="px-4 py-2">
        <div className="font-medium">
          {tree.species} {tree.variety}
        </div>
        <div className="text-[11px] text-muted-foreground">#{tree.tree_id}</div>
      </td>
      <td className="px-3 py-2 capitalize text-muted-foreground">{tree.growth_stage}</td>
      <td className="px-3 py-2">
        {demoEnabled ? (
          <Input
            type="number"
            min={0}
            max={100}
            step={0.1}
            className="h-8 w-20"
            value={value}
            disabled={disabled}
            onChange={(e) => setValue(e.target.value)}
            onBlur={() => {
              const n = Number(value);
              if (!Number.isFinite(n)) return;
              if (tree.current_vwc != null && Math.abs(n - tree.current_vwc) < 0.05) return;
              onVwc(n);
            }}
          />
        ) : (
          <span
            className={cn(
              "font-medium",
              tone === "dry" && "text-amber-600",
              tone === "wet" && "text-sky-600",
              tone === "ok" && "text-emerald-600",
            )}
          >
            {fmt(tree.current_vwc)}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-muted-foreground">{fmt(tree.target_vwc)}</td>
      <td className="px-3 py-2">{fmt(tree.moisture_gap)}</td>
      <td className="px-3 py-2 font-medium">{fmt(tree.deficit_score)}</td>
      <td className="px-3 py-2">
        <Badge variant={tree.sensors[0]?.overridden ? "default" : "muted"}>{source}</Badge>
      </td>
    </tr>
  );
}
