import { NotFoundView } from "@/components/shell/NotFound";

/** notFound() outside the app's pages, which have their own inside the sidebar and header. */
export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center px-4">
      <NotFoundView />
    </main>
  );
}
