"use client";

import * as React from "react";
import { Check, Droplet, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError, irrigationApi } from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import type { ProposalStatus, SupervisorProposal } from "@/lib/types";

const ACTION_LABEL: Record<string, string> = {
  skip_schedule: "Skip the baseline schedule",
  adjust_duration: "Adjust the run duration",
  start_zone_watering: "Emergency run now",
  pass_no_action: "Let the baseline schedule run",
};

const STATUS_STYLE: Record<ProposalStatus, string> = {
  pending: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  executed: "bg-success/10 text-success border-success/30",
  approved: "bg-success/10 text-success border-success/30",
  rejected: "bg-muted text-muted-foreground border-border",
  no_action: "bg-muted text-muted-foreground border-border",
  error: "bg-destructive/10 text-destructive border-destructive/30",
};

export function ProposalCard({
  proposal,
  onResolved,
}: {
  proposal: SupervisorProposal;
  onResolved: () => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = React.useState<"approve" | "reject" | null>(null);
  const { decision, solution } = proposal;
  const isPending = proposal.status === "pending";

  async function act(kind: "approve" | "reject") {
    setBusy(kind);
    try {
      await (kind === "approve"
        ? irrigationApi.approve(proposal.thread_id)
        : irrigationApi.reject(proposal.thread_id));
      toast.success(kind === "approve" ? "Approved & executed" : "Proposal rejected");
      onResolved();
    } catch (err) {
      toast.error(
        `Could not ${kind} the proposal`,
        err instanceof ApiError ? err.detail : undefined,
      );
      setBusy(null);
    }
  }

  const durationLine =
    solution && solution.delta_minutes !== 0
      ? `${solution.baseline_minutes} min → ${solution.recommended_minutes} min` +
        (solution.pulses > 1 ? ` · ${solution.pulses} pulses` : "") +
        ` (${solution.delta_minutes > 0 ? "+" : ""}${solution.delta_minutes} min)`
      : null;

  const headline = proposal.summary || decision?.reason || "";
  const supportingReason =
    decision?.reason && decision.reason !== proposal.summary ? decision.reason : null;

  return (
    <div className="rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Droplet className="size-4 text-primary" />
          <span className="font-medium">Zone {proposal.zone_id}</span>
          <span className="text-xs text-muted-foreground">
            · {new Date(proposal.for_date).toLocaleDateString()}
          </span>
        </div>
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
            STATUS_STYLE[proposal.status],
          )}
        >
          {proposal.status.replace("_", " ")}
        </span>
      </div>

      <p className="mt-2 text-sm font-medium">
        {ACTION_LABEL[proposal.action] ?? proposal.action}
        {proposal.action === "skip_schedule" && decision?.days
          ? ` · ${decision.days} day${decision.days === 1 ? "" : "s"}`
          : ""}
      </p>

      {headline && <p className="mt-2 text-sm leading-relaxed">{headline}</p>}
      {supportingReason && (
        <p className="mt-1 text-sm text-muted-foreground">{supportingReason}</p>
      )}

      {(durationLine || solution) && (
        <div className="mt-3 rounded-md bg-muted/40 p-2.5 text-xs">
          {durationLine && (
            <p className="font-medium text-foreground">Duration: {durationLine}</p>
          )}
          {solution?.per_tree?.length ? (
            <ul className="mt-1 space-y-0.5 text-muted-foreground">
              {solution.per_tree.map((o) => (
                <li key={o.tree_id}>
                  {o.species}: {o.delivered_gal} gal → projected {o.post_vwc}% VWC
                  {o.penalty > 5 ? " ⚠" : ""}
                </li>
              ))}
            </ul>
          ) : null}
          {solution?.rationale && (
            <p className="mt-1 italic text-muted-foreground">{solution.rationale}</p>
          )}
        </div>
      )}

      {proposal.deficit_score != null && (
        <p className="mt-2 text-[11px] text-muted-foreground/80">
          Deficit score: {proposal.deficit_score}
        </p>
      )}

      {isPending && (
        <div className="mt-3 flex justify-end gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={busy !== null}
            onClick={() => act("reject")}
          >
            {busy === "reject" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <X className="size-4" />
            )}
            Reject
          </Button>
          <Button size="sm" disabled={busy !== null} onClick={() => act("approve")}>
            {busy === "approve" ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Check className="size-4" />
            )}
            Approve
          </Button>
        </div>
      )}
    </div>
  );
}
