"use client";

import type { ColumnDef } from "@tanstack/react-table";
import type { Tree, Zone } from "@/lib/types";
import { RowActions, type RowActionHandlers } from "@/components/data-table/row-actions";
import {
  Dash,
  IdBadge,
  NullableText,
  TruncatedText,
} from "@/components/data-table/cells";

export function treeColumns(
  zones: Zone[],
  actions: RowActionHandlers<Tree>,
): ColumnDef<Tree>[] {
  const zoneLabel = (id: number | null) => {
    if (id == null) return null;
    return zones.find((z) => z.zone_id === id)?.name ?? `#${id}`;
  };

  return [
    {
      accessorKey: "tree_id",
      header: "ID",
      cell: ({ row }) => <IdBadge id={row.original.tree_id} />,
    },
    {
      accessorKey: "species",
      header: "Species",
      cell: ({ row }) => (
        <span className="font-medium">{row.original.species}</span>
      ),
    },
    { accessorKey: "variety", header: "Variety" },
    {
      id: "zone",
      header: "Zone",
      accessorFn: (t) => zoneLabel(t.zone_id) ?? "",
      cell: ({ row }) => <NullableText value={zoneLabel(row.original.zone_id)} />,
    },
    {
      accessorKey: "planted_date",
      header: "Planted",
      cell: ({ row }) => <NullableText value={row.original.planted_date} />,
    },
    {
      id: "age",
      header: "Age",
      accessorFn: (t) => t.age_years ?? "",
      cell: ({ row }) =>
        row.original.age_years != null ? (
          <span className="tabular-nums">{row.original.age_years} yr</span>
        ) : (
          <Dash />
        ),
    },
    {
      accessorKey: "additional_context",
      header: "Context",
      cell: ({ row }) => (
        <TruncatedText value={row.original.additional_context} />
      ),
    },
    {
      accessorKey: "notes",
      header: "Notes",
      cell: ({ row }) => <TruncatedText value={row.original.notes} width="max-w-[180px]" />,
    },
    {
      id: "actions",
      header: "",
      enableSorting: false,
      enableGlobalFilter: false,
      cell: ({ row }) => (
        <div className="text-right">
          <RowActions
            row={row.original}
            actions={actions}
            label={`Actions for tree ${row.original.tree_id}`}
          />
        </div>
      ),
    },
  ];
}
