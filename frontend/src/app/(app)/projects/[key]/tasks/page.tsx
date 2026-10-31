import { redirect } from "next/navigation";

/** The tasks crumb on a task page opens the project's board, as the project's own address does. */
export default async function TasksPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  redirect(`/projects/${encodeURIComponent(key)}/board`);
}
