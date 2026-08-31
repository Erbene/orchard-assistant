"use client";

import { Eye, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface RowActionHandlers<T> {
  onView: (row: T) => void;
  onEdit: (row: T) => void;
  onDelete: (row: T) => void;
}

export function RowActions<T>({
  row,
  actions,
  label = "Row actions",
}: {
  row: T;
  actions: RowActionHandlers<T>;
  label?: string;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label={label}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Actions</DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => actions.onView(row)}>
          <Eye /> View details
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => actions.onEdit(row)}>
          <Pencil /> Edit
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          onSelect={() => actions.onDelete(row)}
        >
          <Trash2 /> Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
