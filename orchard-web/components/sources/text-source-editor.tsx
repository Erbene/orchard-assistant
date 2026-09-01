"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Check,
  Clipboard,
  Eraser,
  Monitor,
  Moon,
  Sun,
  Columns2,
  Pencil,
  Eye,
} from "lucide-react";
import type { MDEditorProps } from "@uiw/react-md-editor";
import { cn } from "@/lib/utils";

// The editor bundle only loads in the browser; its stylesheet is safe to
// import here (CSS never runs on the server).
import "@uiw/react-md-editor/markdown-editor.css";

/** `@uiw/react-md-editor` reaches for `window`/`document` on import, so it must
 *  never render on the server. */
const MDEditor = dynamic<MDEditorProps>(
  () => import("@uiw/react-md-editor"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[420px] animate-pulse items-center justify-center rounded-md border bg-muted/40 text-sm text-muted-foreground">
        Loading editor…
      </div>
    ),
  },
);

// --------------------------------------------------------------------------
// Stats
// --------------------------------------------------------------------------

export interface TextSourceStats {
  characters: number;
  charactersNoSpaces: number;
  words: number;
  lines: number;
  /** Rounded up, assuming ~200 wpm. */
  readingTimeMinutes: number;
}

export function computeStats(markdown: string): TextSourceStats {
  const words = markdown.trim() ? markdown.trim().split(/\s+/).length : 0;
  return {
    characters: markdown.length,
    charactersNoSpaces: markdown.replace(/\s/g, "").length,
    words,
    lines: markdown ? markdown.split(/\r\n|\r|\n/).length : 0,
    readingTimeMinutes: Math.max(1, Math.ceil(words / 200)),
  };
}

// --------------------------------------------------------------------------
// Color mode
// --------------------------------------------------------------------------

type ColorMode = "light" | "dark";
type ModePreference = "system" | ColorMode;

function useSystemColorMode(): ColorMode {
  const [mode, setMode] = React.useState<ColorMode>("light");
  React.useEffect(() => {
    const root = document.documentElement;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const resolve = () => {
      if (root.classList.contains("dark")) return setMode("dark");
      if (root.classList.contains("light")) return setMode("light");
      setMode(mq.matches ? "dark" : "light");
    };
    resolve();
    mq.addEventListener("change", resolve);
    const observer = new MutationObserver(resolve);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => {
      mq.removeEventListener("change", resolve);
      observer.disconnect();
    };
  }, []);
  return mode;
}

// --------------------------------------------------------------------------
// Component
// --------------------------------------------------------------------------

type ViewMode = "write" | "split" | "preview";

export interface TextSourceEditorProps {
  /** Controlled Markdown value. Omit for an uncontrolled editor. */
  value?: string;
  /** Fired on every edit with the full Markdown string. */
  onChange?: (markdown: string) => void;
  /** Initial value for the uncontrolled case. */
  defaultValue?: string;
  /** Fired whenever the derived stats change. */
  onStatsChange?: (stats: TextSourceStats) => void;
  placeholder?: string;
  /** Editor pane height in px. Default 420. */
  height?: number;
  /** Force a color mode. Omit to follow `.dark`/`.light` on `<html>` then the OS. */
  colorMode?: ColorMode;
  className?: string;
}

const VIEWS: { id: ViewMode; label: string; icon: React.ReactNode }[] = [
  { id: "write", label: "Write", icon: <Pencil className="size-3.5" /> },
  { id: "split", label: "Split", icon: <Columns2 className="size-3.5" /> },
  { id: "preview", label: "Preview", icon: <Eye className="size-3.5" /> },
];

export function TextSourceEditor({
  value,
  onChange,
  defaultValue = "",
  onStatsChange,
  placeholder = "Paste or write a text source in Markdown — notes, an article, a research summary, a transcript…",
  height = 420,
  colorMode,
  className,
}: TextSourceEditorProps) {
  const isControlled = value !== undefined;
  const [internal, setInternal] = React.useState(defaultValue);
  const markdown = isControlled ? value : internal;

  const setMarkdown = React.useCallback(
    (next: string) => {
      if (!isControlled) setInternal(next);
      onChange?.(next);
    },
    [isControlled, onChange],
  );

  const [view, setView] = React.useState<ViewMode>("write");
  const [preference, setPreference] = React.useState<ModePreference>("system");
  const [copied, setCopied] = React.useState(false);
  const [confirmClear, setConfirmClear] = React.useState(false);

  const systemMode = useSystemColorMode();
  const resolvedMode: ColorMode =
    colorMode ?? (preference === "system" ? systemMode : preference);

  const stats = React.useMemo(() => computeStats(markdown), [markdown]);
  React.useEffect(() => {
    onStatsChange?.(stats);
  }, [stats, onStatsChange]);

  async function copyRaw() {
    try {
      await navigator.clipboard.writeText(markdown);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked (insecure context / permissions) — no-op */
    }
  }

  function clearText() {
    if (!markdown) return;
    if (confirmClear) {
      setMarkdown("");
      setConfirmClear(false);
      return;
    }
    setConfirmClear(true);
    window.setTimeout(() => setConfirmClear(false), 2500);
  }

  function cycleMode() {
    setPreference((p) =>
      p === "system" ? "light" : p === "light" ? "dark" : "system",
    );
  }

  const modeIcon =
    preference === "system" ? (
      <Monitor className="size-3.5" />
    ) : preference === "light" ? (
      <Sun className="size-3.5" />
    ) : (
      <Moon className="size-3.5" />
    );

  const reader = (
    <article
      className={cn(
        "prose prose-sm max-w-none overflow-y-auto rounded-md border bg-background p-4 sm:prose-base",
        "prose-headings:scroll-mt-4 prose-pre:bg-muted prose-pre:text-foreground",
        resolvedMode === "dark" && "prose-invert",
      )}
      style={{ height, maxHeight: height }}
      data-color-mode={resolvedMode}
    >
      {markdown.trim() ? (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
      ) : (
        <p className="italic text-muted-foreground">Nothing to preview yet.</p>
      )}
    </article>
  );

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border bg-card p-2 text-card-foreground",
        className,
      )}
      data-color-mode={resolvedMode}
    >
      {/* toolbar row */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border p-0.5">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setView(v.id)}
              aria-pressed={view === v.id}
              className={cn(
                "inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium transition-colors",
                view === v.id
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {v.icon}
              <span className="hidden sm:inline">{v.label}</span>
            </button>
          ))}
        </div>

        {!colorMode && (
          <IconButton
            onClick={cycleMode}
            title={`Theme: ${preference}`}
            aria-label={`Theme: ${preference}. Click to change.`}
          >
            {modeIcon}
            <span className="hidden capitalize md:inline">{preference}</span>
          </IconButton>
        )}

        <div className="ml-auto flex items-center gap-1.5">
          <IconButton onClick={copyRaw} disabled={!markdown} title="Copy raw Markdown">
            {copied ? (
              <Check className="size-3.5 text-success" />
            ) : (
              <Clipboard className="size-3.5" />
            )}
            <span className="hidden md:inline">
              {copied ? "Copied" : "Copy"}
            </span>
          </IconButton>
          <IconButton
            onClick={clearText}
            disabled={!markdown}
            title="Clear all text"
            className={confirmClear ? "border-destructive text-destructive" : undefined}
          >
            <Eraser className="size-3.5" />
            <span className="hidden md:inline">
              {confirmClear ? "Confirm?" : "Clear"}
            </span>
          </IconButton>
        </div>
      </div>

      {/* body */}
      {view === "preview" ? (
        reader
      ) : view === "split" ? (
        <div className="grid gap-2 lg:grid-cols-2">
          <MDEditor
            value={markdown}
            onChange={(next) => setMarkdown(next ?? "")}
            height={height}
            preview="edit"
            textareaProps={{ placeholder }}
          />
          {reader}
        </div>
      ) : (
        <MDEditor
          value={markdown}
          onChange={(next) => setMarkdown(next ?? "")}
          height={height}
          preview="edit"
          textareaProps={{ placeholder }}
        />
      )}

      {/* stats bar */}
      <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs text-muted-foreground">
        <Stat label="words" value={stats.words} />
        <Stat label="characters" value={stats.characters} />
        <Stat label="no spaces" value={stats.charactersNoSpaces} />
        <Stat label="lines" value={stats.lines} />
        <Stat label="min read" value={stats.readingTimeMinutes} />
      </dl>
    </div>
  );
}

export default TextSourceEditor;

// --------------------------------------------------------------------------
// Local primitives
// --------------------------------------------------------------------------

function IconButton({
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium transition-colors",
        "hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-40",
        className,
      )}
    />
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline gap-1">
      <dd className="font-medium tabular-nums text-foreground">
        {value.toLocaleString()}
      </dd>
      <dt>{label}</dt>
    </div>
  );
}
