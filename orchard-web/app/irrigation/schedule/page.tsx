"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { irrigationApi } from "@/lib/api";
import type { IrrigationOverview } from "@/lib/types";
import { ScheduleConfig } from "@/components/irrigation/schedule-config";

export default function IrrigationSchedulePage() {
  const [overview, setOverview] = React.useState<IrrigationOverview | null>(null);

  const load = React.useCallback(async () => {
    const ov = await irrigationApi.overview();
    setOverview(ov);
  }, []);

  React.useEffect(() => {
    void load().catch(() => setOverview(null));
  }, [load]);

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-2xl">
        {!overview ? (
          <div className="flex justify-center py-16">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <ScheduleConfig
            zones={overview.zones}
            supervisor={overview.supervisor}
            onChange={load}
          />
        )}
      </div>
    </div>
  );
}
