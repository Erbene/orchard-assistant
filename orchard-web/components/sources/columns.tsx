"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { FileText, Type } from "lucide-react";
import type { Source } from "@/lib/types";
import { RowActions, type RowActionHandlers } from "@/components/data-table/row-actions";
import { IdBadge, TruncatedText } from "@/components/data-table/cells";
import { Badge } from "@/components/ui/badge";

export function sourceColumns(
  actions: RowActionHandlers<Source>,
): ColumnDef<Source>[] {
  return [
    {
      accessorKey: "id",
      header: "ID",
      cell: ({ row }) => <IdBadge id={row.original.id} />,
    },
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
    },
    {
      accessorKey: "source_type",
      header: "Type",
      cell: ({ row }) => (
        <Badge variant="secondary" className="gap-1 font-normal">
          {row.original.source_type === "file" ? (
            <FileText className="size-3" />
          ) : (
            <Type className="size-3" />
          )}
          {row.original.source_type}
        </Badge>
      ),
    },
    {
      accessorKey: "file_path",
      header: "File",
      cell: ({ row }) => <TruncatedText value={row.original.file_path} width="max-w-[240px]" />,
    },
    {
      accessorKey: "upload_date",
      header: "Uploaded",
      cell: ({ row }) => (
        <span className="tabular-nums text-muted-foreground">
          {row.original.upload_date.slice(0, 10)}
        </span>
      ),
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
            label={`Actions for source ${row.original.id}`}
          />
        </div>
      ),
    },
  ];
}
