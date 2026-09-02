"use client";

import * as React from "react";

/** "Thinking" with dots cycling . -> .. -> ... -> . while the assistant works. */
export function ThinkingDots({ label = "Thinking" }: { label?: string }) {
  const [count, setCount] = React.useState(1);

  React.useEffect(() => {
    const id = setInterval(() => setCount((n) => (n % 3) + 1), 400);
    return () => clearInterval(id);
  }, []);

  return (
    <p
      className="flex items-center leading-relaxed text-muted-foreground"
      aria-label={`${label}…`}
    >
      {label}
      <span aria-hidden className="inline-block w-5 text-left">
        {".".repeat(count)}
      </span>
    </p>
  );
}
