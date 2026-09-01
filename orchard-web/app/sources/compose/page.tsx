"use client";

/**
 * Example page: compose a text-based knowledge source in Markdown, watch its
 * live stats, and save it into the RAG knowledge base.
 *
 * Shows how a parent owns the editor state (`markdown`) and reads derived
 * state (`stats`) via the component's callbacks.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Download, Loader2, Save } from "lucide-react";
import {
  TextSourceEditor,
  computeStats,
  type TextSourceStats,
} from "@/components/sources/text-source-editor";
import { useToast } from "@/components/ui/toast";
import { ApiError, sourcesApi } from "@/lib/api";

const SAMPLE = `# Field notes — North Block, week 34

Overcast, ~24 °C. Kent mangos on the north row are holding fruit well.

## Observations
- Slight leaf curl on tree #12 — check irrigation emitter.
- **Anthracnose** spotting on two lower branches; earmark for a copper spray.
- Soil probe reads dry at 20 cm depth across the block.

## Follow-ups
1. Deep-water the north row.
2. Prune and bag the affected sapodilla branches.
3. Re-scout in 7 days.
`;

export default function ComposeSourcePage() {
  const router = useRouter();
  const toast = useToast();

  const [name, setName] = React.useState("");
  const [markdown, setMarkdown] = React.useState(SAMPLE);
  const [stats, setStats] = React.useState<TextSourceStats>(() =>
    computeStats(SAMPLE),
  );
  const [saving, setSaving] = React.useState(false);

  const canSave = name.trim().length > 0 && markdown.trim().length > 0 && !saving;

  async function save() {
    setSaving(true);
    try {
      const source = await sourcesApi.ingestText(name.trim(), markdown);
      toast.success("Source ingested", `${source.name} (#${source.id})`);
      router.push("/sources");
    } catch (err) {
      toast.error(
        "Could not save source",
        err instanceof ApiError ? err.detail : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  function downloadMarkdown() {
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(name.trim() || "source").replace(/[^\w.-]+/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <header className="flex flex-wrap items-center gap-3 border-b px-6 py-4">
        <Link
          href="/sources"
          className="inline-flex size-8 items-center justify-center rounded-md border text-muted-foreground transition-colors hover:bg-accent"
          aria-label="Back to sources"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <div className="mr-auto">
          <h1 className="text-lg font-semibold">Compose text source</h1>
          <p className="text-sm text-muted-foreground">
            ~{stats.words.toLocaleString()} words · {stats.readingTimeMinutes} min
            read
          </p>
        </div>
        <button
          type="button"
          onClick={downloadMarkdown}
          disabled={!markdown.trim()}
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-accent disabled:opacity-40"
        >
          <Download className="size-4" /> .md
        </button>
        <button
          type="button"
          onClick={save}
          disabled={!canSave}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Save className="size-4" />
          )}
          Save to knowledge base
        </button>
      </header>

      <div className="mx-auto w-full max-w-4xl space-y-4 p-6">
        <div className="space-y-1.5">
          <label htmlFor="source-name" className="text-sm font-medium">
            Source name
          </label>
          <input
            id="source-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Field notes — North Block, week 34"
            className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>

        <TextSourceEditor
          value={markdown}
          onChange={setMarkdown}
          onStatsChange={setStats}
          height={480}
        />
      </div>
    </div>
  );
}
