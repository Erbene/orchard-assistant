"use client";

import * as React from "react";
import Link from "next/link";
import { PenLine, Plus } from "lucide-react";
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
import dynamic from "next/dynamic";
import { SourceUploadForm } from "@/components/sources/source-upload-form";
import { sourceColumns } from "@/components/sources/columns";

// markdown renderer (~react-markdown + remark-gfm) — only needed when the
// details dialog is open, so keep it out of the initial page bundle.
const SourceContent = dynamic(
  () =>
    import("@/components/sources/source-content").then((m) => m.SourceContent),
  { loading: () => <p className="text-sm text-muted-foreground">Loading…</p> },
);
import { ApiError, sourcesApi } from "@/lib/api";
import type { Source, SourceDetail } from "@/lib/types";

export default function SourcesPage() {
  const toast = useToast();
  const [sources, setSources] = React.useState<Source[]>([]);
  const [loading, setLoading] = React.useState(true);

  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [viewing, setViewing] = React.useState<SourceDetail | null>(null);
  const [renaming, setRenaming] = React.useState<Source | null>(null);
  const [renameValue, setRenameValue] = React.useState("");
  const [deleting, setDeleting] = React.useState<Source | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      setSources(await sourcesApi.list());
    } catch (err) {
      toast.error(
        "Could not load sources",
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
      sourceColumns({
        onView: async (s) => {
          try {
            setViewing(await sourcesApi.get(s.id));
          } catch {
            toast.error("Could not open source");
          }
        },
        onEdit: (s) => {
          setRenaming(s);
          setRenameValue(s.name);
        },
        onDelete: setDeleting,
      }),
    [toast],
  );

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-6 py-4">
        <h1 className="text-lg font-semibold">Knowledge Sources</h1>
        <p className="text-sm text-muted-foreground">
          Documents chunked into the RAG knowledge base. Link them to trees to
          scope the agronomist agent&apos;s retrieval.
        </p>
      </header>

      <div className="flex-1 overflow-auto p-6">
        <DataTable
          columns={columns}
          data={sources}
          isLoading={loading}
          searchPlaceholder="Search sources…"
          emptyMessage="No sources yet — add one to get started."
          toolbar={
            <div className="flex gap-2">
              <Button variant="outline" asChild>
                <Link href="/sources/compose">
                  <PenLine className="size-4" /> Compose
                </Link>
              </Button>
              <Button onClick={() => setUploadOpen(true)}>
                <Plus className="size-4" /> Add Source
              </Button>
            </div>
          }
        />
      </div>

      {/* upload / paste modal */}
      <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add knowledge source</DialogTitle>
          </DialogHeader>
          <SourceUploadForm
            onCancel={() => setUploadOpen(false)}
            onCreated={() => {
              setUploadOpen(false);
              void refresh();
            }}
          />
        </DialogContent>
      </Dialog>

      {/* rename modal */}
      <Dialog
        open={renaming !== null}
        onOpenChange={(o) => !o && setRenaming(null)}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Rename source</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!renaming) return;
              try {
                await sourcesApi.rename(renaming.id, renameValue.trim());
                toast.success("Source renamed");
                setRenaming(null);
                void refresh();
              } catch (err) {
                toast.error(
                  "Rename failed",
                  err instanceof ApiError ? err.detail : undefined,
                );
              }
            }}
          >
            <input
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setRenaming(null)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={!renameValue.trim()}>
                Save
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <DetailsDialog
        open={viewing !== null}
        onOpenChange={(o) => !o && setViewing(null)}
        title={viewing ? viewing.name : ""}
        description={viewing ? `Source #${viewing.id}` : undefined}
        className="sm:max-w-3xl"
        fields={
          viewing
            ? [
                ["Type", viewing.source_type],
                [
                  "Uploaded",
                  viewing.upload_date.slice(0, 19).replace("T", " "),
                ],
                ["File", viewing.file_path],
              ]
            : []
        }
        content={
          viewing ? <SourceContent markdown={viewing.raw_content} /> : null
        }
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete source?"
        description={
          deleting
            ? `#${deleting.id} · ${deleting.name} — its chunks are removed from the vector store and unlinked from all trees.`
            : undefined
        }
        confirmLabel="Delete"
        destructive
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await sourcesApi.remove(deleting.id);
            toast.success("Source deleted", `#${deleting.id}`);
            setDeleting(null);
            void refresh();
          } catch (err) {
            toast.error(
              "Could not delete source",
              err instanceof ApiError ? err.detail : undefined,
            );
          }
        }}
      />
    </div>
  );
}
