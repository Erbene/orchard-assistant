"use client";

import * as React from "react";
import { Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { ApiError, sourcesApi } from "@/lib/api";
import type { Source } from "@/lib/types";

type Mode = "file" | "text";

export function SourceUploadForm({
  onCreated,
  onCancel,
}: {
  onCreated: (source: Source) => void;
  onCancel?: () => void;
}) {
  const toast = useToast();
  const [mode, setMode] = React.useState<Mode>("file");
  const [name, setName] = React.useState("");
  const [text, setText] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const label =
      name.trim() || (mode === "file" ? file?.name ?? "" : "Pasted note");
    if (mode === "file" && !file) return setError("Choose a PDF, MD or TXT file.");
    if (mode === "text" && !text.trim()) return setError("Paste some text.");

    setBusy(true);
    try {
      const source =
        mode === "file"
          ? await sourcesApi.ingestFile(label, file!)
          : await sourcesApi.ingestText(label, text);
      toast.success("Source ingested", `${source.name} (#${source.id})`);
      onCreated(source);
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Upload failed.";
      setError(msg);
      toast.error("Could not ingest source", msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <div className="inline-flex rounded-md border p-0.5 text-sm">
        {(["file", "text"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              "rounded px-3 py-1 capitalize transition-colors",
              mode === m
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {m === "file" ? "Upload file" : "Paste text"}
          </button>
        ))}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="source-name">Name</Label>
        <Input
          id="source-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={mode === "file" ? "defaults to the file name" : "e.g. Mango pruning guide"}
          autoComplete="off"
        />
      </div>

      {mode === "file" ? (
        <div className="space-y-1.5">
          <Label htmlFor="source-file">File (PDF, MD, TXT)</Label>
          <Input
            id="source-file"
            type="file"
            accept=".pdf,.md,.markdown,.txt,.rst,.csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label htmlFor="source-text">Text</Label>
          <Textarea
            id="source-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            placeholder="Paste agronomy notes, an extension bulletin, cultivar guidance…"
          />
        </div>
      )}

      {error && (
        <p
          role="alert"
          className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
      )}

      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
        <Button type="submit" disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <Upload className="size-4" />}
          Ingest source
        </Button>
      </div>
    </form>
  );
}
