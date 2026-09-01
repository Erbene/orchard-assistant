"use client";

import * as React from "react";
import { Check, Loader2, Library } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { ApiError, sourcesApi, treesApi } from "@/lib/api";
import type { Source } from "@/lib/types";

/**
 * Multi-select for associating knowledge-base sources with one tree.
 * Loads the full source catalogue + the tree's current links, lets the user
 * toggle, and PUTs the new full set.
 */
export function LinkedSources({ treeId }: { treeId: number }) {
  const toast = useToast();
  const [all, setAll] = React.useState<Source[]>([]);
  const [selected, setSelected] = React.useState<Set<number>>(new Set());
  const [initial, setInitial] = React.useState<Set<number>>(new Set());
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [catalogue, linked] = await Promise.all([
          sourcesApi.list(),
          treesApi.linkedSources(treeId),
        ]);
        if (cancelled) return;
        setAll(catalogue);
        const ids = new Set(linked.map((s) => s.id));
        setSelected(ids);
        setInitial(ids);
      } catch (err) {
        if (!cancelled)
          toast.error(
            "Could not load sources",
            err instanceof ApiError ? err.detail : undefined,
          );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [treeId, toast]);

  const dirty =
    selected.size !== initial.size ||
    [...selected].some((id) => !initial.has(id));

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    try {
      await treesApi.setLinkedSources(treeId, [...selected]);
      setInitial(new Set(selected));
      toast.success("Linked sources updated");
    } catch (err) {
      toast.error(
        "Could not update links",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <Library className="size-4" /> Linked sources
        </p>
        <Button
          size="sm"
          variant="outline"
          onClick={save}
          disabled={!dirty || saving}
        >
          {saving && <Loader2 className="size-3.5 animate-spin" />}
          Save links
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        </div>
      ) : all.length === 0 ? (
        <p className="rounded-md border px-3 py-2 text-xs text-muted-foreground">
          No sources yet — add some on the Sources page.
        </p>
      ) : (
        <ul className="max-h-44 space-y-1 overflow-y-auto rounded-md border p-1">
          {all.map((s) => {
            const on = selected.has(s.id);
            return (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => toggle(s.id)}
                  aria-pressed={on}
                  className={cn(
                    "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors",
                    on ? "bg-primary/10 text-primary" : "hover:bg-accent",
                  )}
                >
                  <span
                    className={cn(
                      "flex size-4 shrink-0 items-center justify-center rounded border",
                      on ? "border-primary bg-primary text-primary-foreground" : "border-input",
                    )}
                  >
                    {on && <Check className="size-3" />}
                  </span>
                  <span className="truncate">{s.name}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {s.source_type}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
