"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
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
import type { ZoneOption } from "@/components/forms/tree-entity-form";
import { ApiError, treesApi, zonesApi } from "@/lib/api";
import type { RachioZone, Tree } from "@/lib/types";
import { zoneDisplayName } from "@/lib/zone-label";

export default function TreesPage() {
  const toast = useToast();
  const router = useRouter();
  const [trees, setTrees] = React.useState<Tree[]>([]);
  const [zones, setZones] = React.useState<RachioZone[]>([]);
  const [zoneOptions, setZoneOptions] = React.useState<ZoneOption[]>([]);
  const [loading, setLoading] = React.useState(true);

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Tree | null>(null);
  const [viewing, setViewing] = React.useState<Tree | null>(null);
  const [deleting, setDeleting] = React.useState<Tree | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const t = await treesApi.list();
      setTrees(t);
    } catch (err) {
      toast.error(
        "Could not load trees",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setLoading(false);
    }
    // zones are optional context (Rachio may be unconfigured) - don't block trees
    try {
      const devices = await zonesApi.list();
      setZones(devices.flatMap((d) => d.zones));
      setZoneOptions(
        devices.flatMap((d) =>
          d.zones.map((z) => ({
            id: z.id,
            label: `${d.name} · ${zoneDisplayName(z) ?? z.id}`,
          })),
        ),
      );
    } catch {
      setZones([]);
      setZoneOptions([]);
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

  const zoneLabel = (tree: Tree) =>
    tree.zone_display_name ??
    zoneDisplayName(
      tree.zone_id ? zones.find((z) => z.id === tree.zone_id) : null,
      tree.zone_id,
    );

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-6 py-4">
        <h1 className="text-lg font-semibold">Trees</h1>
        <p className="text-sm text-muted-foreground">
          Tree records. Each tree can be bound to a Rachio irrigation zone.
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
            zoneOptions={zoneOptions}
            tree={editing}
            onCancel={() => setFormOpen(false)}
            onSaved={(saved) => {
              const wasCreate = !editing;
              setFormOpen(false);
              setEditing(null);
              void refresh();
              if (wasCreate) {
                // land on the new tree's Care Plan tab and auto-generate
                router.push(`/trees/${saved.tree_id}?tab=care-plan&autogen=1`);
              }
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
                ["Zone", zoneLabel(viewing)],
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
