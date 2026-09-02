"use client";

import * as React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CarePlanTab } from "@/components/care-plan/care-plan-tab";
import { LinkedSources } from "./LinkedSources";

export function TreeDetailBody({
  treeId,
  initialTab,
  autoGenerate,
}: {
  treeId: number;
  initialTab: string;
  autoGenerate: boolean;
}) {
  const [tab, setTab] = React.useState(
    initialTab === "care-plan" ? "care-plan" : "sources",
  );

  return (
    <Tabs value={tab} onValueChange={setTab} className="space-y-5">
      <TabsList>
        <TabsTrigger value="sources">Knowledge sources</TabsTrigger>
        <TabsTrigger value="care-plan">Care Plan</TabsTrigger>
      </TabsList>

      <TabsContent value="sources">
        <LinkedSources treeId={treeId} />
      </TabsContent>

      <TabsContent value="care-plan">
        <CarePlanTab treeId={treeId} autoGenerate={autoGenerate} />
      </TabsContent>
    </Tabs>
  );
}
