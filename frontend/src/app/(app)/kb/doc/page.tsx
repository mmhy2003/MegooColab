import { redirect } from "next/navigation";

/** The doc crumb on a document opens the Knowledge Base. */
export default function KbDocPage() {
  redirect("/kb");
}
