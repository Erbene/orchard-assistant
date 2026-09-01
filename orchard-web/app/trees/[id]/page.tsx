import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { TreeHeader } from "./components/TreeHeader";
import { LinkedSources } from "./components/LinkedSources";

export default async function TreeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const treeId = Number(id);

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
          <LinkedSources treeId={treeId} />
        </div>
      </div>
    </div>
  );
}
