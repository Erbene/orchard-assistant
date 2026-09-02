"use client";

import * as React from "react";
import { Loader2, MessageSquare, Plus, Trash2 } from "lucide-react";
import { conversationsApi } from "@/lib/api";
import type { Conversation } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export interface ConversationRailHandle {
  refresh: () => void;
}

interface Props {
  activeId: number | null;
  onSelect: (id: number) => void;
  onNew: () => void;
}

export const ConversationRail = React.forwardRef<ConversationRailHandle, Props>(
  function ConversationRail({ activeId, onSelect, onNew }, ref) {
    const [items, setItems] = React.useState<Conversation[] | null>(null);

    const load = React.useCallback(() => {
      conversationsApi
        .list()
        .then(setItems)
        .catch(() => setItems([]));
    }, []);

    React.useEffect(() => load(), [load]);
    React.useImperativeHandle(ref, () => ({ refresh: load }), [load]);

    const remove = async (id: number) => {
      await conversationsApi.remove(id).catch(() => {});
      if (id === activeId) onNew();
      load();
    };

    return (
      <div className="flex h-full w-64 shrink-0 flex-col border-r bg-muted/20">
        <div className="p-2">
          <Button
            onClick={onNew}
            variant="outline"
            size="sm"
            className="w-full justify-start gap-2"
          >
            <Plus className="size-4" />
            New chat
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {items === null ? (
            <div className="flex justify-center p-4">
              <Loader2 className="size-4 animate-spin text-muted-foreground" />
            </div>
          ) : items.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">
              No conversations yet.
            </p>
          ) : (
            <ul className="space-y-0.5">
              {items.map((c) => (
                <li
                  key={c.id}
                  onClick={() => onSelect(c.id)}
                  className={cn(
                    "group flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                    c.id === activeId
                      ? "bg-accent font-medium"
                      : "hover:bg-accent/60",
                  )}
                >
                  <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">{c.title}</span>
                  <button
                    type="button"
                    aria-label={`Delete "${c.title}"`}
                    onClick={(e) => {
                      e.stopPropagation();
                      void remove(c.id);
                    }}
                    className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  },
);
