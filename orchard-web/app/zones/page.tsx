"use client";

import * as React from "react";
import { Droplet, ExternalLink, Info, Loader2, RefreshCw } from "lucide-react";
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
import { useToast } from "@/components/ui/toast";
import { ApiError, zonesApi } from "@/lib/api";
import type { RachioCustom, RachioDevice, RachioZone } from "@/lib/types";

const RACHIO_APP_URL = "https://app.rach.io";

function customName(c: RachioCustom | null): string {
  return (c && typeof c.name === "string" && c.name) || "—";
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

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-start justify-between gap-4 border-b px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold">Irrigation zones</h1>
          <p className="text-sm text-muted-foreground">
            Live from your Rachio account · read-only
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
        {/* read-only notice — zone config is edited only in the Rachio app */}
        <div className="flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-primary" />
          <p className="text-muted-foreground">
            Zone configuration (names, vegetation type, soil, nozzles, slope,
            sun exposure) is <strong className="text-foreground">read-only</strong>{" "}
            here. To change any of it, use the official{" "}
            <a
              href={RACHIO_APP_URL}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-0.5 font-medium text-primary hover:underline"
            >
              Rachio app <ExternalLink className="size-3" />
            </a>
            . The only action available here is a manual watering run.
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
          devices.map((device) => (
            <section key={device.id} className="rounded-lg border">
              <div className="flex items-center justify-between border-b bg-muted/40 px-4 py-2.5">
                <div>
                  <h2 className="font-medium">{device.name}</h2>
                  <p className="text-xs text-muted-foreground">
                    {device.model ?? "Rachio controller"}
                  </p>
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
                      <th>Zone</th>
                      <th>Vegetation</th>
                      <th>Soil</th>
                      <th>Nozzle</th>
                      <th>Slope</th>
                      <th>Sun</th>
                      <th className="text-right">Water</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {device.zones.map((zone) => (
                      <tr
                        key={zone.id}
                        className="[&>td]:px-4 [&>td]:py-2 [&>td]:align-top"
                      >
                        <td className="tabular-nums text-muted-foreground">
                          {zone.zone_number}
                        </td>
                        <td>
                          <span className="font-medium">{zone.name}</span>
                          {!zone.enabled && (
                            <Badge variant="muted" className="ml-2">
                              disabled
                            </Badge>
                          )}
                        </td>
                        <td className="text-muted-foreground">
                          {customName(zone.custom_crop)}
                        </td>
                        <td className="text-muted-foreground">
                          {customName(zone.custom_soil)}
                        </td>
                        <td className="text-muted-foreground">
                          {customName(zone.custom_nozzle)}
                        </td>
                        <td className="text-muted-foreground">
                          {customName(zone.custom_slope)}
                        </td>
                        <td className="text-muted-foreground">
                          {customName(zone.custom_shade)}
                        </td>
                        <td className="text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!zone.enabled}
                            title={
                              zone.enabled
                                ? "Start a manual watering run"
                                : "Zone is disabled in Rachio"
                            }
                            onClick={() => setWatering(zone)}
                          >
                            <Droplet className="size-3.5" /> Water
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))
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
      onDone(zone.name, minutes);
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
          <DialogTitle>Water “{zone?.name}”</DialogTitle>
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
