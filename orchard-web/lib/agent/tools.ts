/**
 * Tool metadata shared between the server route (app/api/chat/route.ts) and
 * the client-side rendering widgets. No React, no SDK imports - safe on both
 * sides of the network boundary.
 */

/** Result values the client sends back for a human-in-the-loop tool. */
export const APPROVAL = {
  YES: "APPROVED",
  NO: "REJECTED",
} as const;

export type ApprovalDecision = (typeof APPROVAL)[keyof typeof APPROVAL];

/**
 * Tools that require explicit human approval before they run. These are
 * declared on the server WITHOUT an `execute` fn, so the SDK forwards the
 * call to the client; the client renders an <ApprovalCard/> and the approved
 * action is executed server-side by `executeApprovedToolCalls`.
 */
export const HUMAN_APPROVAL_TOOLS = ["deleteZone", "triggerIrrigation"] as const;
export type HumanApprovalTool = (typeof HUMAN_APPROVAL_TOOLS)[number];

export function isHumanApprovalTool(name: string): name is HumanApprovalTool {
  return (HUMAN_APPROVAL_TOOLS as readonly string[]).includes(name);
}

/** Human-readable status text for the inline tool-call widget. */
export const TOOL_PRESENTATION: Record<
  string,
  { running: string; done: string; impact: "read" | "write" | "high" }
> = {
  validateInput: {
    running: "Validating input…",
    done: "Input validated",
    impact: "read",
  },
  listZones: {
    running: "Querying zones…",
    done: "Zones loaded",
    impact: "read",
  },
  listTrees: {
    running: "Querying tree records…",
    done: "Tree records loaded",
    impact: "read",
  },
  createTree: {
    running: "Creating tree record…",
    done: "Tree record created",
    impact: "write",
  },
  updateZone: {
    running: "Updating zone…",
    done: "Zone updated",
    impact: "write",
  },
  deleteZone: {
    running: "Awaiting approval to delete zone…",
    done: "Delete zone",
    impact: "high",
  },
  triggerIrrigation: {
    running: "Awaiting approval to start irrigation…",
    done: "Trigger irrigation",
    impact: "high",
  },
};

export function toolPresentation(name: string) {
  return (
    TOOL_PRESENTATION[name] ?? {
      running: `Running ${name}…`,
      done: name,
      impact: "read" as const,
    }
  );
}
