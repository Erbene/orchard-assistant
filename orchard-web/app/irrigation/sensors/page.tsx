"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { irrigationApi } from "@/lib/api";
import type { IrrigationOverview } from "@/lib/types";
import { SensorsPanel } from "@/components/irrigation/sensors-panel";

export default function IrrigationSensorsPage() {
  const [overview, setOverview] = React.useState<IrrigationOverview | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void irrigationApi
      .overview()
      .then((ov) => {
        if (!cancelled) setOverview(ov);
      })
      .catch(() => {
        if (!cancelled) setOverview(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-4xl">
        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <SensorsPanel demoEnabled={Boolean(overview?.demo_enabled)} />
        )}
      </div>
    </div>
  );
}
