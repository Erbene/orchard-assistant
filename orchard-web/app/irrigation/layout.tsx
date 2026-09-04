"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Droplets, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { ApiError, irrigationApi } from "@/lib/api";
import type { SupervisorProposal } from "@/lib/types";

const IrrigationNavRefreshContext = React.createContext<(() => void) | null>(null);

export function useIrrigationNavRefresh() {
  return React.useContext(IrrigationNavRefreshContext);
}

export default function IrrigationLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const [proposals, setProposals] = React.useState<SupervisorProposal[]>([]);
  const [running, setRunning] = React.useState(false);

  const loadProposals = React.useCallback(async () => {
    const ps = await irrigationApi.proposals();
    setProposals(ps);
  }, []);

  React.useEffect(() => {
    void loadProposals().catch(() => setProposals([]));
  }, [loadProposals, pathname]);

  async function runSupervision() {
    setRunning(true);
    try {
      const res = await irrigationApi.runSupervisor();
      const pending = res.proposals.filter((p) => p.status === "pending").length;
      toast.success(
        "Supervision complete",
        `${res.proposals.length} zone${res.proposals.length === 1 ? "" : "s"} reviewed · ${pending} awaiting approval`,
      );
      await loadProposals();
      if (pending > 0) router.push("/irrigation");
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

  return (
    <IrrigationNavRefreshContext.Provider value={loadProposals}>
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
            <SubNavLink
              href="/irrigation"
              active={pathname === "/irrigation"}
            >
              Approval queue
              {pending.length > 0 && (
                <span className="ml-1.5 rounded-full bg-amber-500/15 px-1.5 text-[11px] font-medium text-amber-600">
                  {pending.length}
                </span>
              )}
            </SubNavLink>
            <SubNavLink
              href="/irrigation/sensors"
              active={pathname.startsWith("/irrigation/sensors")}
            >
              Sensors
            </SubNavLink>
            <SubNavLink
              href="/irrigation/schedule"
              active={pathname.startsWith("/irrigation/schedule")}
            >
              Schedule &amp; settings
            </SubNavLink>
          </div>
        </div>

        {children}
      </div>
    </IrrigationNavRefreshContext.Provider>
  );
}

function SubNavLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={
        "flex items-center border-b-2 px-3 py-2.5 text-sm font-medium transition-colors " +
        (active
          ? "border-primary text-foreground"
          : "border-transparent text-muted-foreground hover:text-foreground")
      }
    >
      {children}
    </Link>
  );
}
