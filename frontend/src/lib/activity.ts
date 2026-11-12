import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type ActivityCount = components["schemas"]["ActivityCount"];

/** How many of a task's Activity entries came after the one at (at, id); the server counts no further than 100. */
export async function countActivityAfter(taskKey: string, at: string, id: string): Promise<number> {
  const params = new URLSearchParams({ after: at, after_id: id });
  return (await api<ActivityCount>(`/api/tasks/${taskKey}/activity/count?${params}`)).count;
}
