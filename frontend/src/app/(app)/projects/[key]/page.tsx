import { redirect } from "next/navigation";

/** A project's own address opens its board. */
export default async function ProjectPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  redirect(`/projects/${encodeURIComponent(key)}/board`);
}
