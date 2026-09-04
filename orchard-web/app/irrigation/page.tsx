"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { irrigationApi } from "@/lib/api";
import type { SupervisorProposal } from "@/lib/types";
import { ProposalCard } from "@/components/irrigation/proposal-card";
import { useIrrigationNavRefresh } from "./layout";

export default function IrrigationPage() {
  const refreshNav = useIrrigationNavRefresh();
  const [proposals, setProposals] = React.useState<SupervisorProposal[]>([]);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    const ps = await irrigationApi.proposals();
    setProposals(ps);
    refreshNav?.();
  }, [refreshNav]);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void load()
      .catch(() => {
        if (!cancelled) setProposals([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const pending = proposals.filter((p) => p.status === "pending");
  const resolved = proposals.filter((p) => p.status !== "pending");

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-2xl">
        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : proposals.length === 0 ? (
          <div className="rounded-lg border border-dashed py-16 text-center text-sm text-muted-foreground">
            No proposals yet. Run the supervision task to review your zones.
          </div>
        ) : (
          <div className="space-y-6">
            {pending.length > 0 && (
              <section className="space-y-3">
                <h2 className="text-sm font-semibold">
                  Awaiting approval ({pending.length})
                </h2>
                {pending.map((p) => (
                  <ProposalCard key={p.thread_id} proposal={p} onResolved={load} />
                ))}
              </section>
            )}
            {resolved.length > 0 && (
              <section className="space-y-3">
                <h2 className="text-sm font-semibold text-muted-foreground">
                  Recent
                </h2>
                {resolved.slice(0, 10).map((p) => (
                  <ProposalCard key={p.thread_id} proposal={p} onResolved={load} />
                ))}
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
