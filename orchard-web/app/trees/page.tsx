"use client";

import * as React from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DetailsDialog } from "@/components/ui/details-dialog";
import { DataTable } from "@/components/ui/data-table";
import { useToast } from "@/components/ui/toast";
import { TreeEntityForm } from "@/components/forms/tree-entity-form";
import { treeColumns } from "@/components/trees/columns";
import { ApiError, treesApi, zonesApi } from "@/lib/api";
import type { Tree, Zone } from "@/lib/types";

export default function TreesPage() {
  const toast = useToast();
  const [trees, setTrees] = React.useState<Tree[]>([]);
  const [zones, setZones] = React.useState<Zone[]>([]);
  const [loading, setLoading] = React.useState(true);

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Tree | null>(null);
  const [viewing, setViewing] = React.useState<Tree | null>(null);
  const [deleting, setDeleting] = React.useState<Tree | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const [t, z] = await Promise.all([treesApi.list(), zonesApi.list()]);
      setTrees(t);
      setZones(z);
    } catch (err) {
      toast.error(
        "Could not load trees",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  const columns = React.useMemo(
    () =>
      treeColumns(zones, {
        onView: setViewing,
        onEdit: (t) => {
          setEditing(t);
          setFormOpen(true);
        },
        onDelete: setDeleting,
      }),
    [zones],
  );

  const zoneLabel = (id: number | null) =>
    id == null
      ? null
      : (zones.find((z) => z.zone_id === id)?.name ?? `#${id}`);

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-6 py-4">
        <h1 className="text-lg font-semibold">Trees</h1>
        <p className="text-sm text-muted-foreground">
          Tree records across all zones.
        </p>
      </header>

      <div className="flex-1 overflow-auto p-6">
        <DataTable
          columns={columns}
          data={trees}
          isLoading={loading}
          searchPlaceholder="Search trees…"
          emptyMessage="No tree records yet."
          toolbar={
            <Button
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus className="size-4" /> Add New Record
            </Button>
          }
        />
      </div>

      <Dialog
        open={formOpen}
        onOpenChange={(o) => {
          setFormOpen(o);
          if (!o) setEditing(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing ? `Edit tree #${editing.tree_id}` : "New tree record"}
            </DialogTitle>
          </DialogHeader>
          <TreeEntityForm
            zones={zones}
            tree={editing}
            onCancel={() => setFormOpen(false)}
            onSaved={() => {
              setFormOpen(false);
              setEditing(null);
              void refresh();
            }}
          />
        </DialogContent>
      </Dialog>

      <DetailsDialog
        open={viewing !== null}
        onOpenChange={(o) => !o && setViewing(null)}
        title={viewing ? `Tree #${viewing.tree_id}` : ""}
        fields={
          viewing
            ? [
                ["ID", `#${viewing.tree_id}`],
                ["Species", viewing.species],
                ["Variety", viewing.variety],
                ["Zone", zoneLabel(viewing.zone_id)],
                ["Planted date", viewing.planted_date],
                [
                  "Age",
                  viewing.age_years != null
                    ? `${viewing.age_years} yr (${viewing.age_days} days)`
                    : null,
                ],
                ["Additional context", viewing.additional_context],
                ["Notes", viewing.notes],
              ]
            : []
        }
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete tree record?"
        description={
          deleting
            ? `#${deleting.tree_id} · ${deleting.species} · ${deleting.variety}`
            : undefined
        }
        confirmLabel="Delete"
        destructive
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await treesApi.remove(deleting.tree_id);
            toast.success("Tree record deleted", `#${deleting.tree_id}`);
            setDeleting(null);
            void refresh();
          } catch (err) {
            toast.error(
              "Could not delete tree",
              err instanceof ApiError ? err.detail : undefined,
            );
          }
        }}
      />
    </div>
  );
}
