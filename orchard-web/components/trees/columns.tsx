"use client";

import Link from "next/link";
import { ClipboardList, Library } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import type { RachioZone, Tree } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { RowActions, type RowActionHandlers } from "@/components/data-table/row-actions";
import {
  Dash,
  IdBadge,
  NullableText,
  TruncatedText,
} from "@/components/data-table/cells";

export function treeColumns(
  zones: RachioZone[],
  actions: RowActionHandlers<Tree>,
): ColumnDef<Tree>[] {
  const zoneLabel = (id: string | null) => {
    if (!id) return null;
    return zones.find((z) => z.id === id)?.name ?? id;
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
        <div className="flex items-center justify-end gap-1">
          <Button
            asChild
            variant="ghost"
            size="icon"
            className="size-8"
            title="Linked sources"
          >
            <Link
              href={`/trees/${row.original.tree_id}?tab=sources`}
              aria-label={`Linked sources for tree ${row.original.tree_id}`}
            >
              <Library className="size-4" />
            </Link>
          </Button>
          <Button
            asChild
            variant="ghost"
            size="icon"
            className="relative size-8"
            title={
              row.original.has_care_plan
                ? "Edit care plan"
                : "Generate care plan"
            }
          >
            <Link
              href={`/trees/${row.original.tree_id}?tab=care-plan`}
              aria-label={`Care plan for tree ${row.original.tree_id}`}
            >
              <ClipboardList className="size-4" />
              {row.original.has_care_plan && (
                <span className="absolute right-1 top-1 size-1.5 rounded-full bg-primary" />
              )}
            </Link>
          </Button>
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
