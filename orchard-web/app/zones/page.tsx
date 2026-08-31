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
import { ZoneEntityForm } from "@/components/forms/zone-entity-form";
import { zoneColumns } from "@/components/zones/columns";
import { ApiError, zonesApi } from "@/lib/api";
import type { Zone } from "@/lib/types";

export default function ZonesPage() {
  const toast = useToast();
  const [zones, setZones] = React.useState<Zone[]>([]);
  const [loading, setLoading] = React.useState(true);

  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Zone | null>(null);
  const [viewing, setViewing] = React.useState<Zone | null>(null);
  const [deleting, setDeleting] = React.useState<Zone | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      setZones(await zonesApi.list());
    } catch (err) {
      toast.error(
        "Could not load zones",
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
      zoneColumns({
        onView: setViewing,
        onEdit: (z) => {
          setEditing(z);
          setFormOpen(true);
        },
        onDelete: setDeleting,
      }),
    [],
  );

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-6 py-4">
        <h1 className="text-lg font-semibold">Zones</h1>
        <p className="text-sm text-muted-foreground">
          Orchard zones. Ids are assigned automatically.
        </p>
      </header>

      <div className="flex-1 overflow-auto p-6">
        <DataTable
          columns={columns}
          data={zones}
          isLoading={loading}
          searchPlaceholder="Search zones…"
          emptyMessage="No zones yet."
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
              {editing ? `Edit zone #${editing.zone_id}` : "New zone"}
            </DialogTitle>
          </DialogHeader>
          <ZoneEntityForm
            zone={editing}
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
        title={viewing ? `Zone #${viewing.zone_id}` : ""}
        fields={
          viewing
            ? [
                ["ID", `#${viewing.zone_id}`],
                ["Name", viewing.name],
                ["Soil drainage", viewing.soil_drainage],
                ["Water Source", viewing.water_source],
              ]
            : []
        }
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete zone?"
        description={
          deleting ? `#${deleting.zone_id} · ${deleting.name}` : undefined
        }
        confirmLabel="Delete"
        destructive
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await zonesApi.remove(deleting.zone_id);
            toast.success("Zone deleted", `#${deleting.zone_id}`);
            setDeleting(null);
            void refresh();
          } catch (err) {
            toast.error(
              "Could not delete zone",
              err instanceof ApiError ? err.detail : undefined,
            );
          }
        }}
      />
    </div>
  );
}
