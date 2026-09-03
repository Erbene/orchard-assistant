"use client";

import * as React from "react";
import { Droplets, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { ApiError, irrigationApi } from "@/lib/api";
import type { IrrigationOverview, SupervisorProposal } from "@/lib/types";
import { ProposalCard } from "@/components/irrigation/proposal-card";
import { ScheduleConfig } from "@/components/irrigation/schedule-config";
import { DemoScenarios } from "@/components/irrigation/demo-scenarios";

export default function IrrigationPage() {
  const toast = useToast();
  const [overview, setOverview] = React.useState<IrrigationOverview | null>(null);
  const [proposals, setProposals] = React.useState<SupervisorProposal[]>([]);
  const [running, setRunning] = React.useState(false);
  const [tab, setTab] = React.useState<"queue" | "schedule">("queue");

  const load = React.useCallback(async () => {
    const [ov, ps] = await Promise.all([
      irrigationApi.overview(),
      irrigationApi.proposals(),
    ]);
    setOverview(ov);
    setProposals(ps);
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function runSupervision() {
    setRunning(true);
    try {
      const res = await irrigationApi.runSupervisor();
      const pending = res.proposals.filter((p) => p.status === "pending").length;
      toast.success(
        "Supervision complete",
        `${res.proposals.length} zone${res.proposals.length === 1 ? "" : "s"} reviewed · ${pending} awaiting approval`,
      );
      await load();
      if (pending > 0) setTab("queue");
    } catch (err) {
      toast.error(
        "Supervision failed",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setRunning(false);
    }
  }

  const pending = proposals.filter((p) => p.status === "pending");
  const resolved = proposals.filter((p) => p.status !== "pending");

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b px-6 py-4">
        <div className="flex-1">
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            <Droplets className="size-5" /> Irrigation
          </h1>
          <p className="text-sm text-muted-foreground">
            The supervisor intercepts the baseline Rachio schedule to save
            water. Every action it proposes needs your approval.
          </p>
        </div>
        <Button onClick={runSupervision} disabled={running} className="gap-1.5">
          {running ? (
            <>
              <Loader2 className="size-4 animate-spin" /> Running…
            </>
          ) : (
            <>
              <Play className="size-4" /> Run Supervision Task
            </>
          )}
        </Button>
      </header>

      <div className="border-b px-6">
        <div className="flex gap-1">
          <TabButton active={tab === "queue"} onClick={() => setTab("queue")}>
            Approval queue
            {pending.length > 0 && (
              <span className="ml-1.5 rounded-full bg-amber-500/15 px-1.5 text-[11px] font-medium text-amber-600">
                {pending.length}
              </span>
            )}
          </TabButton>
          <TabButton active={tab === "schedule"} onClick={() => setTab("schedule")}>
            Schedule &amp; settings
          </TabButton>
        </div>
      </div>

      {overview?.demo_enabled && <DemoScenarios onApplied={load} />}

      <div className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-2xl">
          {!overview ? (
            <div className="flex justify-center py-16">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          ) : tab === "schedule" ? (
            <ScheduleConfig
              zones={overview.zones}
              supervisor={overview.supervisor}
              onChange={load}
            />
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
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "flex items-center border-b-2 px-3 py-2.5 text-sm font-medium transition-colors " +
        (active
          ? "border-primary text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground")
      }
    >
      {children}
    </button>
  );
}
