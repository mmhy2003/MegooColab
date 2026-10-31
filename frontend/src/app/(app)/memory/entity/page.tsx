import { redirect } from "next/navigation";

/** The entity crumb on a memory entity opens Memory. */
export default function MemoryEntityPage() {
  redirect("/memory");
}
