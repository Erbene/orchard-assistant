"use client";

import type { ColumnDef } from "@tanstack/react-table";
import type { Zone } from "@/lib/types";
import { RowActions, type RowActionHandlers } from "@/components/data-table/row-actions";
import { IdBadge, NullableText } from "@/components/data-table/cells";

export function zoneColumns(
  actions: RowActionHandlers<Zone>,
): ColumnDef<Zone>[] {
  return [
    {
      accessorKey: "zone_id",
      header: "ID",
      cell: ({ row }) => <IdBadge id={row.original.zone_id} />,
    },
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => (
        <span className="font-medium">{row.original.name}</span>
      ),
    },
    {
      accessorKey: "soil_drainage",
      header: "Soil drainage",
      cell: ({ row }) => <NullableText value={row.original.soil_drainage} />,
    },
    {
      accessorKey: "water_source",
      header: "Water Source",
      cell: ({ row }) => <NullableText value={row.original.water_source} />,
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
            label={`Actions for zone ${row.original.zone_id}`}
          />
        </div>
      ),
    },
  ];
}
