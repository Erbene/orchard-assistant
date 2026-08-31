"use client";

import * as React from "react";
import { Plus, RefreshCw, Pencil, Trash2, Loader2, TreePine, Map } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { TreeEntityForm } from "@/components/forms/tree-entity-form";
import { ZoneEntityForm } from "@/components/forms/zone-entity-form";
import { ApiError, treesApi, zonesApi } from "@/lib/api";
import type { Tree, Zone } from "@/lib/types";

type Editing =
  | { kind: "tree"; record: Tree | null }
  | { kind: "zone"; record: Zone | null }
  | null;

export function EntityManager() {
  const toast = useToast();
  const [zones, setZones] = React.useState<Zone[]>([]);
  const [trees, setTrees] = React.useState<Tree[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [editing, setEditing] = React.useState<Editing>(null);
  const [pendingDelete, setPendingDelete] = React.useState<string | number | null>(
    null,
  );

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [z, t] = await Promise.all([zonesApi.list(), treesApi.list()]);
      setZones(z);
      setTrees(t);
    } catch (err) {
      setLoadError(
        err instanceof ApiError
          ? err.detail
          : "Could not reach the orchard-server API.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  async function deleteZone(id: number) {
    setPendingDelete(id);
    try {
      await zonesApi.remove(id);
      toast.success("Zone deleted", `#${id}`);
      await refresh();
    } catch (err) {
      toast.error(
        "Could not delete zone",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setPendingDelete(null);
    }
  }

  async function deleteTree(id: number) {
    setPendingDelete(id);
    try {
      await treesApi.remove(id);
      toast.success("Tree record deleted", `#${id}`);
      await refresh();
    } catch (err) {
      toast.error(
        "Could not delete tree",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setPendingDelete(null);
    }
  }

  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>Orchard records</CardTitle>
          <CardDescription>Manual create, update and delete.</CardDescription>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refresh()}
          disabled={loading}
        >
          <RefreshCw className={loading ? "animate-spin" : undefined} />
          Refresh
        </Button>
      </CardHeader>

      <CardContent className="flex-1 overflow-y-auto">
        {loadError && (
          <p
            role="alert"
            className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          >
            {loadError}
          </p>
        )}

        <Tabs defaultValue="trees">
          <TabsList>
            <TabsTrigger value="trees">
              <TreePine className="mr-1 size-4" /> Trees
              <Badge variant="muted" className="ml-2">
                {trees.length}
              </Badge>
            </TabsTrigger>
            <TabsTrigger value="zones">
              <Map className="mr-1 size-4" /> Zones
              <Badge variant="muted" className="ml-2">
                {zones.length}
              </Badge>
            </TabsTrigger>
          </TabsList>

          {/* Trees ------------------------------------------------------- */}
          <TabsContent value="trees" className="space-y-3">
            <div className="flex justify-end">
              <Button
                size="sm"
                onClick={() => setEditing({ kind: "tree", record: null })}
              >
                <Plus /> New tree
              </Button>
            </div>

            {editing?.kind === "tree" && (
              <FormPanel
                title={editing.record ? "Edit tree record" : "New tree record"}
              >
                <TreeEntityForm
                  zones={zones}
                  tree={editing.record}
                  onCancel={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    void refresh();
                  }}
                />
              </FormPanel>
            )}

            <ul className="divide-y rounded-md border">
              {trees.map((tree) => (
                <li
                  key={tree.tree_id}
                  className="flex items-center justify-between gap-3 p-3 text-sm"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {tree.species} · {tree.variety}{" "}
                      <span className="text-muted-foreground">#{tree.tree_id}</span>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {tree.zone_id ? `Zone ${tree.zone_id}` : "Unassigned"}
                      {tree.age_years != null && ` · ${tree.age_years} yr`}
                      {tree.planted_date && ` · planted ${tree.planted_date}`}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Edit tree ${tree.tree_id}`}
                      onClick={() => setEditing({ kind: "tree", record: tree })}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete tree ${tree.tree_id}`}
                      onClick={() => void deleteTree(tree.tree_id)}
                      disabled={pendingDelete === tree.tree_id}
                    >
                      {pendingDelete === tree.tree_id ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Trash2 className="size-4 text-destructive" />
                      )}
                    </Button>
                  </div>
                </li>
              ))}
              {!loading && trees.length === 0 && (
                <li className="p-4 text-center text-sm text-muted-foreground">
                  No tree records yet.
                </li>
              )}
            </ul>
          </TabsContent>

          {/* Zones ----------------------------------------------------- */}
          <TabsContent value="zones" className="space-y-3">
            <div className="flex justify-end">
              <Button
                size="sm"
                onClick={() => setEditing({ kind: "zone", record: null })}
              >
                <Plus /> New zone
              </Button>
            </div>

            {editing?.kind === "zone" && (
              <FormPanel
                title={editing.record ? "Edit zone" : "New zone"}
              >
                <ZoneEntityForm
                  zone={editing.record}
                  onCancel={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    void refresh();
                  }}
                />
              </FormPanel>
            )}

            <ul className="divide-y rounded-md border">
              {zones.map((zone) => (
                <li
                  key={zone.zone_id}
                  className="flex items-center justify-between gap-3 p-3 text-sm"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {zone.name}{" "}
                      <span className="text-muted-foreground">
                        #{zone.zone_id}
                      </span>
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {zone.soil_drainage ?? "drainage unknown"}
                      {zone.source && ` · source: ${zone.source}`}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Edit zone ${zone.zone_id}`}
                      onClick={() => setEditing({ kind: "zone", record: zone })}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete zone ${zone.zone_id}`}
                      onClick={() => void deleteZone(zone.zone_id)}
                      disabled={pendingDelete === zone.zone_id}
                    >
                      {pendingDelete === zone.zone_id ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Trash2 className="size-4 text-destructive" />
                      )}
                    </Button>
                  </div>
                </li>
              ))}
              {!loading && zones.length === 0 && (
                <li className="p-4 text-center text-sm text-muted-foreground">
                  No zones yet.
                </li>
              )}
            </ul>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function FormPanel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border bg-muted/30 p-4">
      <h4 className="mb-3 text-sm font-semibold">{title}</h4>
      {children}
    </div>
  );
}
