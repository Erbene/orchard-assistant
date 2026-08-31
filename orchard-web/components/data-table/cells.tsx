import { cn } from "@/lib/utils";

export function Dash() {
  return <span className="text-muted-foreground">—</span>;
}

export function NullableText({
  value,
  className,
}: {
  value: string | null | undefined;
  className?: string;
}) {
  if (!value) return <Dash />;
  return <span className={className}>{value}</span>;
}

/** Single-line truncated cell with the full value on hover. */
export function TruncatedText({
  value,
  width = "max-w-[220px]",
}: {
  value: string | null | undefined;
  width?: string;
}) {
  if (!value) return <Dash />;
  return (
    <span
      title={value}
      className={cn("block truncate text-muted-foreground", width)}
    >
      {value}
    </span>
  );
}

export function IdBadge({ id }: { id: number }) {
  return <span className="tabular-nums text-muted-foreground">#{id}</span>;
}
