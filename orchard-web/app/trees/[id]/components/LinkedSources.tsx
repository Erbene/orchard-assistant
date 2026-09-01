"use client";

import * as React from "react";
import { Reorder, useDragControls } from "framer-motion";
import { GripVertical, Library, Loader2, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { ApiError, treesApi } from "@/lib/api";
import type { Source } from "@/lib/types";
import { AddSourceModal } from "./AddSourceModal";

function sameOrder(a: Source[], b: Source[]): boolean {
  return a.length === b.length && a.every((s, i) => s.id === b[i]?.id);
}

/**
 * Ordered, drag-reorderable list of the knowledge sources linked to one tree.
 * The list order IS the authority ranking (#1 = highest); "Save Changes" PUTs
 * the ordered id array to `PUT /api/v1/trees/{id}/sources`.
 */
export function LinkedSources({ treeId }: { treeId: number }) {
  const toast = useToast();
  const [rows, setRows] = React.useState<Source[]>([]);
  const [baseline, setBaseline] = React.useState<Source[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [modalOpen, setModalOpen] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    treesApi
      .linkedSources(treeId)
      .then((linked) => {
        if (cancelled) return;
        setRows(linked);
        setBaseline(linked);
      })
      .catch(
        (err: unknown) =>
          !cancelled &&
          toast.error(
            "Could not load linked sources",
            err instanceof ApiError ? err.detail : undefined,
          ),
      )
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [treeId, toast]);

  const dirty = !sameOrder(rows, baseline);
  const linkedIds = React.useMemo(
    () => new Set(rows.map((s) => s.id)),
    [rows],
  );

  function unlink(id: number) {
    setRows((prev) => prev.filter((s) => s.id !== id));
  }

  function addSource(source: Source) {
    setRows((prev) =>
      prev.some((s) => s.id === source.id) ? prev : [...prev, source],
    );
  }

  async function save() {
    setSaving(true);
    try {
      const updated = await treesApi.setLinkedSources(
        treeId,
        rows.map((s) => s.id),
      );
      setRows(updated);
      setBaseline(updated);
      toast.success("Source priority saved");
    } catch (err) {
      toast.error(
        "Could not save changes",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold">
            <Library className="size-4" /> Linked sources
          </h2>
          <p className="text-xs text-muted-foreground">
            Drag to rank. Higher = more authority; conflicts resolve in favour
            of #1.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setModalOpen(true)}>
          <Plus className="size-3.5" /> Add Source
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-6">
          <Loader2 className="size-4 animate-spin text-muted-foreground" />
        </div>
      ) : rows.length === 0 ? (
        <p className="rounded-md border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">
          No sources linked. Click “Add Source” to ground this tree’s advice.
        </p>
      ) : (
        <Reorder.Group
          axis="y"
          values={rows}
          onReorder={setRows}
          className="space-y-1.5"
        >
          {rows.map((source, index) => (
            <SourceRow
              key={source.id}
              source={source}
              rank={index + 1}
              onUnlink={() => unlink(source.id)}
            />
          ))}
        </Reorder.Group>
      )}

      <div className="flex justify-end">
        <Button onClick={save} disabled={!dirty || saving}>
          {saving && <Loader2 className="size-3.5 animate-spin" />}
          Save Changes
        </Button>
      </div>

      <AddSourceModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        linkedIds={linkedIds}
        onAdd={addSource}
      />
    </section>
  );
}

function SourceRow({
  source,
  rank,
  onUnlink,
}: {
  source: Source;
  rank: number;
  onUnlink: () => void;
}) {
  const controls = useDragControls();

  return (
    <Reorder.Item
      value={source}
      dragListener={false}
      dragControls={controls}
      className="flex items-center gap-2 rounded-md border bg-card px-2 py-2 text-sm shadow-sm"
    >
      <button
        type="button"
        aria-label={`Reorder ${source.name}`}
        onPointerDown={(e) => controls.start(e)}
        className="cursor-grab touch-none text-muted-foreground active:cursor-grabbing"
      >
        <GripVertical className="size-4" />
      </button>

      <Badge variant="secondary" className="shrink-0 tabular-nums">
        #{rank}
      </Badge>

      <span className="truncate font-medium">{source.name}</span>

      <Badge variant="muted" className="ml-auto shrink-0 uppercase">
        {source.source_type}
      </Badge>

      <button
        type="button"
        aria-label={`Unlink ${source.name}`}
        onClick={onUnlink}
        className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
      >
        <X className="size-3.5" />
      </button>
    </Reorder.Item>
  );
}
