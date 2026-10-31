import { notFound } from "next/navigation";

/** Any address no page matches: the not-found page, inside the app's sidebar and header. */
export default function MissingPage() {
  notFound();
}
