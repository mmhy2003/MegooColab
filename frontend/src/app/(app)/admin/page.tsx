import { redirect } from "next/navigation";

/** The admin crumb opens the first admin page. */
export default function AdminPage() {
  redirect("/admin/users");
}
