import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { TreeHeader } from "./components/TreeHeader";
import { TreeDetailBody } from "./components/TreeDetailBody";

export default async function TreeDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const treeId = Number(id);
  const tab = typeof sp.tab === "string" ? sp.tab : "sources";
  const autoGenerate = sp.autogen === "1";

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-6 py-4">
        <Link
          href="/trees"
          className="mb-2 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Trees
        </Link>
        <TreeHeader treeId={treeId} />
      </header>

      <div className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-2xl">
          <TreeDetailBody
            treeId={treeId}
            initialTab={tab}
            autoGenerate={autoGenerate}
          />
        </div>
      </div>
    </div>
  );
}
