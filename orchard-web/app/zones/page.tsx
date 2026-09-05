"use client";

import * as React from "react";
import {
  ChevronDown,
  Droplet,
  ExternalLink,
  EyeOff,
  Info,
  Loader2,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useToast } from "@/components/ui/toast";
import { ApiError, zonesApi } from "@/lib/api";
import type { RachioDevice, RachioZone } from "@/lib/types";
import { zoneDisplayName } from "@/lib/zone-label";

const RACHIO_APP_URL = "https://app.rach.io";

function patchZone(
  devices: RachioDevice[],
  zoneId: string,
  patch: Partial<RachioZone>,
): RachioDevice[] {
  return devices.map((d) => ({
    ...d,
    zones: d.zones.map((z) => (z.id === zoneId ? { ...z, ...patch } : z)),
  }));
}

export default function ZonesPage() {
  const toast = useToast();
  const [devices, setDevices] = React.useState<RachioDevice[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<{ status: number; detail: string } | null>(
    null,
  );
  const [watering, setWatering] = React.useState<RachioZone | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDevices(await zonesApi.list());
    } catch (err) {
      if (err instanceof ApiError) setError({ status: err.status, detail: err.detail });
      else setError({ status: 0, detail: "Could not load zones." });
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const activeDevices = React.useMemo(
    () =>
      devices
        .map((d) => ({ ...d, zones: d.zones.filter((z) => z.in_use !== false) }))
        .filter((d) => d.zones.length > 0),
    [devices],
  );
  const unusedEntries = React.useMemo(
    () =>
      devices.flatMap((d) =>
        d.zones
          .filter((z) => z.in_use === false)
          .map((zone) => ({ device: d, zone })),
      ),
    [devices],
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start justify-between gap-4 border-b px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">Irrigation zones</h1>
          <p className="text-sm text-muted-foreground">
            Live from your Rachio account. Add a local label, or mark a zone
            not in use so it stays off planning.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => void refresh()}
          disabled={loading}
        >
          <RefreshCw className="size-3.5" /> Refresh
        </Button>
      </header>

      <div className="flex-1 space-y-4 overflow-auto p-6">
        <div className="flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-primary" />
          <p className="text-muted-foreground">
            Zone hardware settings are{" "}
            <strong className="text-foreground">read-only</strong> here. To
            change them, use the official{" "}
            <a
              href={RACHIO_APP_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline"
            >
              Rachio app <ExternalLink className="size-3" />
            </a>
            . Unused zones do not appear in irrigation planning or tree
            pickers.
          </p>
        </div>

        {loading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : error ? (
          <div className="rounded-md border border-dashed px-4 py-10 text-center text-sm">
            {error.status === 503 ? (
              <>
                <p className="font-medium">Rachio isn’t connected</p>
                <p className="mt-1 text-muted-foreground">
                  Set <code className="rounded bg-muted px-1">RACHIO_API_KEY</code>{" "}
                  on the server to see your controllers and zones.
                </p>
              </>
            ) : (
              <p className="text-destructive">{error.detail}</p>
            )}
          </div>
        ) : devices.length === 0 ? (
          <p className="rounded-md border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
            No Rachio devices found on this account.
          </p>
        ) : (
          <>
            {activeDevices.length === 0 ? (
              <p className="rounded-md border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
                Every zone is marked not in use. Restore one below to bring it
                back into planning.
              </p>
            ) : (
              activeDevices.map((device) => (
                <DeviceZoneTable
                  key={device.id}
                  device={device}
                  unused={false}
                  onPatch={(zoneId, patch) =>
                    setDevices((prev) => patchZone(prev, zoneId, patch))
                  }
                  onWater={setWatering}
                />
              ))
            )}

            {unusedEntries.length > 0 && (
              <UnusedZones
                entries={unusedEntries}
                onPatch={(zoneId, patch) =>
                  setDevices((prev) => patchZone(prev, zoneId, patch))
                }
                onWater={setWatering}
              />
            )}
          </>
        )}
      </div>

      <WaterZoneDialog
        zone={watering}
        onClose={() => setWatering(null)}
        onDone={(name, minutes) =>
          toast.success("Watering started", `${name} · ${minutes} min`)
        }
        onError={(detail) => toast.error("Could not start watering", detail)}
      />
    </div>
  );
}

function UnusedZones({
  entries,
  onPatch,
  onWater,
}: {
  entries: { device: RachioDevice; zone: RachioZone }[];
  onPatch: (zoneId: string, patch: Partial<RachioZone>) => void;
  onWater: (zone: RachioZone) => void;
}) {
  const byDevice = React.useMemo(() => {
    const map = new Map<string, { device: RachioDevice; zones: RachioZone[] }>();
    for (const { device, zone } of entries) {
      const row = map.get(device.id) ?? { device, zones: [] };
      row.zones.push(zone);
      map.set(device.id, row);
    }
    return [...map.values()];
  }, [entries]);

  return (
    <Collapsible className="rounded-lg border">
      <CollapsibleTrigger className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm font-medium hover:bg-muted/40 [&[data-state=open]>svg]:rotate-180">
        <span>
          Unused zones
          <span className="ml-2 text-muted-foreground">({entries.length})</span>
        </span>
        <ChevronDown className="size-4 text-muted-foreground transition-transform" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-3 border-t p-3">
          {byDevice.map(({ device, zones }) => (
            <DeviceZoneTable
              key={device.id}
              device={{ ...device, zones }}
              unused
              onPatch={onPatch}
              onWater={onWater}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function DeviceZoneTable({
  device,
  unused,
  onPatch,
  onWater,
}: {
  device: RachioDevice;
  unused: boolean;
  onPatch: (zoneId: string, patch: Partial<RachioZone>) => void;
  onWater: (zone: RachioZone) => void;
}) {
  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between border-b bg-muted/40 px-4 py-2.5">
        <div>
          <h2 className="font-medium">{device.name}</h2>
        </div>
        <Badge
          variant={device.status === "ONLINE" ? "success" : "muted"}
          className="uppercase"
        >
          {device.status}
        </Badge>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="[&>th]:px-4 [&>th]:py-2 [&>th]:font-medium">
              <th>#</th>
              <th>Label</th>
              <th>Rachio name</th>
              <th className="w-0 whitespace-nowrap">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {device.zones.map((zone) => (
              <tr
                key={zone.id}
                className="[&>td]:px-4 [&>td]:py-2 [&>td]:align-middle"
              >
                <td className="tabular-nums text-muted-foreground">
                  {zone.zone_number}
                </td>
                <td>
                  <ZoneLabelEditor
                    zone={zone}
                    onSaved={(label, displayName) =>
                      onPatch(zone.id, { label, display_name: displayName })
                    }
                  />
                </td>
                <td>
                  <span className="text-muted-foreground">{zone.name}</span>
                  {!zone.enabled && (
                    <Badge variant="muted" className="ml-2">
                      disabled
                    </Badge>
                  )}
                </td>
                <td className="w-0 whitespace-nowrap">
                  <div className="flex justify-start gap-2">
                    <InUseButton zone={zone} unused={unused} onPatch={onPatch} />
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!zone.enabled}
                      title={
                        zone.enabled
                          ? "Start a manual watering run"
                          : "Zone is disabled in Rachio"
                      }
                      onClick={() => onWater(zone)}
                    >
                      <Droplet className="size-3.5" /> Water Now
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function InUseButton({
  zone,
  unused,
  onPatch,
}: {
  zone: RachioZone;
  unused: boolean;
  onPatch: (zoneId: string, patch: Partial<RachioZone>) => void;
}) {
  const toast = useToast();
  const [saving, setSaving] = React.useState(false);

  async function toggle() {
    const next = unused;
    setSaving(true);
    try {
      const saved = await zonesApi.setInUse(zone.id, next);
      onPatch(zone.id, { in_use: saved.in_use });
    } catch (err) {
      toast.error(
        unused ? "Could not restore zone" : "Could not hide zone",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Button
      size="sm"
      variant="outline"
      disabled={saving}
      onClick={() => void toggle()}
    >
      {saving ? (
        <Loader2 className="size-3.5 animate-spin" />
      ) : unused ? (
        <RotateCcw className="size-3.5" />
      ) : (
        <EyeOff className="size-3.5" />
      )}
      {unused ? "Use again" : "Not in use"}
    </Button>
  );
}

function WaterZoneDialog({
  zone,
  onClose,
  onDone,
  onError,
}: {
  zone: RachioZone | null;
  onClose: () => void;
  onDone: (zoneName: string, minutes: number) => void;
  onError: (detail?: string) => void;
}) {
  const [minutes, setMinutes] = React.useState(5);
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    if (zone) setMinutes(5);
  }, [zone]);

  async function run() {
    if (!zone) return;
    setSubmitting(true);
    try {
      await zonesApi.water(zone.id, minutes);
      onDone(zoneDisplayName(zone) ?? zone.name, minutes);
      onClose();
    } catch (err) {
      onError(err instanceof ApiError ? err.detail : undefined);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={zone !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Water “{zone ? zoneDisplayName(zone) : ""}”</DialogTitle>
          <DialogDescription>
            Starts a manual run on this Rachio zone now. This turns on real
            irrigation hardware.
          </DialogDescription>
        </DialogHeader>

        <label className="text-sm font-medium" htmlFor="water-minutes">
          Duration (minutes)
        </label>
        <Input
          id="water-minutes"
          type="number"
          min={1}
          max={180}
          value={minutes}
          onChange={(e) =>
            setMinutes(Math.max(1, Math.min(180, Number(e.target.value) || 1)))
          }
        />

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={run} disabled={submitting}>
            {submitting && <Loader2 className="size-3.5 animate-spin" />}
            <Droplet className="size-3.5" /> Start watering
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ZoneLabelEditor({
  zone,
  onSaved,
}: {
  zone: RachioZone;
  onSaved: (label: string | null, displayName: string) => void;
}) {
  const toast = useToast();
  const [value, setValue] = React.useState(zone.label ?? "");
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setValue(zone.label ?? "");
  }, [zone.label, zone.id]);

  async function save() {
    const next = value.trim() || null;
    if (next === (zone.label?.trim() || null)) return;
    setSaving(true);
    try {
      const saved = await zonesApi.setLabel(zone.id, next);
      onSaved(saved.label, saved.display_name);
    } catch (err) {
      toast.error(
        "Could not save label",
        err instanceof ApiError ? err.detail : undefined,
      );
      setValue(zone.label ?? "");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Input
      className="h-8 w-44"
      value={value}
      disabled={saving}
      placeholder={zoneDisplayName({ zone_number: zone.zone_number }, zone.id) ?? ""}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => void save()}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.currentTarget.blur();
        }
      }}
    />
  );
}
