"use client";

import * as React from "react";
import { FileText, Loader2, Search } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { ApiError, sourcesApi } from "@/lib/api";
import type { Source } from "@/lib/types";

interface AddSourceModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** ids already on the tree — hidden-disabled in the list */
  linkedIds: Set<number>;
  onAdd: (source: Source) => void;
}

export function AddSourceModal({
  open,
  onOpenChange,
  linkedIds,
  onAdd,
}: AddSourceModalProps) {
  const [catalogue, setCatalogue] = React.useState<Source[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    if (!open) return;
    setQuery("");
    setError(null);
    let cancelled = false;
    sourcesApi
      .list()
      .then((rows) => !cancelled && setCatalogue(rows))
      .catch(
        (err: unknown) =>
          !cancelled &&
          setError(
            err instanceof ApiError ? err.detail : "Could not load sources",
          ),
      );
    return () => {
      cancelled = true;
    };
  }, [open]);

  const results = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return (catalogue ?? []).filter(
      (s) => !q || s.name.toLowerCase().includes(q),
    );
  }, [catalogue, query]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add a knowledge source</DialogTitle>
          <DialogDescription>
            Pick from the knowledge base. New sources append to the bottom of
            the list (lowest authority) — reorder after adding.
          </DialogDescription>
        </DialogHeader>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sources…"
            className="pl-8"
          />
        </div>

        <div className="max-h-72 overflow-y-auto rounded-md border">
          {error ? (
            <p className="px-3 py-6 text-center text-sm text-destructive">
              {error}
            </p>
          ) : catalogue === null ? (
            <div className="flex justify-center py-6">
              <Loader2 className="size-4 animate-spin text-muted-foreground" />
            </div>
          ) : results.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              {catalogue.length === 0
                ? "No sources yet — add some on the Sources page."
                : "No matches."}
            </p>
          ) : (
            <ul className="divide-y">
              {results.map((s) => {
                const linked = linkedIds.has(s.id);
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      disabled={linked}
                      onClick={() => {
                        onAdd(s);
                        onOpenChange(false);
                      }}
                      className={cn(
                        "flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors",
                        linked
                          ? "cursor-not-allowed text-muted-foreground"
                          : "hover:bg-accent",
                      )}
                    >
                      <FileText className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">{s.name}</span>
                      <Badge
                        variant="muted"
                        className="ml-auto shrink-0 uppercase"
                      >
                        {s.source_type}
                      </Badge>
                      {linked && (
                        <span className="shrink-0 text-xs">Linked</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
