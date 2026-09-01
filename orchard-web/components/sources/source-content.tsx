"use client";

import * as React from "react";
import { Code2, Eye } from "lucide-react";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/markdown";

/**
 * A source's `raw_content` — rendered as Markdown by default, with a toggle to
 * inspect the raw text (useful for transcripts / notes where hard line breaks
 * matter).
 */
export function SourceContent({ markdown }: { markdown: string }) {
  const [raw, setRaw] = React.useState(false);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Content
        </p>
        <div className="inline-flex rounded-md border p-0.5 text-xs">
          <Toggle active={!raw} onClick={() => setRaw(false)}>
            <Eye className="size-3" /> Rendered
          </Toggle>
          <Toggle active={raw} onClick={() => setRaw(true)}>
            <Code2 className="size-3" /> Raw
          </Toggle>
        </div>
      </div>

      <div className="max-h-[55vh] overflow-y-auto rounded-md border bg-background p-4">
        {raw ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">
            {markdown}
          </pre>
        ) : (
          <Markdown>{markdown}</Markdown>
        )}
      </div>
    </div>
  );
}

function Toggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1 rounded px-2 py-0.5 transition-colors",
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
