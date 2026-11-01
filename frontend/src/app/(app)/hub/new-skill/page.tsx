"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { SkillUpload } from "@/components/hub/SkillUpload";
import { PageHeader } from "@/components/ui/PageHeader";
import { hubKeys } from "@/lib/hub";
import { usePageTitle } from "@/lib/title";

export default function NewSkillPage() {
  usePageTitle("Add skill", "Tool Hub");
  const router = useRouter();
  const client = useQueryClient();
  return (
    <div className="max-w-3xl">
      <PageHeader title="Add skill" subtitle="Its name and description come from the SKILL.md at the top of the folder." />
      <div className="card p-4">
        <SkillUpload
          onDone={async (tool) => {
            await client.invalidateQueries({ queryKey: hubKeys.all });
            router.push(`/hub/${tool.id}`);
          }}
        />
      </div>
    </div>
  );
}
