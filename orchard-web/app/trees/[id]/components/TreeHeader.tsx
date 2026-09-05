"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { ApiError, treesApi } from "@/lib/api";
import type { Tree } from "@/lib/types";

/** Compact identity strip for the tree detail page. */
export function TreeHeader({ treeId }: { treeId: number }) {
  const [tree, setTree] = React.useState<Tree | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    treesApi
      .get(treeId)
      .then((t) => !cancelled && setTree(t))
      .catch(
        (err: unknown) =>
          !cancelled &&
          setError(err instanceof ApiError ? err.detail : "Failed to load tree"),
      );
    return () => {
      cancelled = true;
    };
  }, [treeId]);

  if (error) {
    return <h1 className="text-lg font-semibold text-destructive">{error}</h1>;
  }
  if (!tree) {
    return (
      <h1 className="flex items-center gap-2 text-lg font-semibold text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Tree #{treeId}
      </h1>
    );
  }

  const age = tree.age_years != null ? `${tree.age_years} yr` : null;

  return (
    <div>
      <h1 className="text-lg font-semibold">
        {tree.species}{" "}
        <span className="font-normal text-muted-foreground">
          · {tree.variety}
        </span>
      </h1>
      <p className="text-sm text-muted-foreground">
        Tree #{tree.tree_id}
        {tree.zone_id != null &&
          ` · ${tree.zone_display_name ?? `Zone ${tree.zone_id}`}`}
        {age && ` · ${age}`}
      </p>
    </div>
  );
}
