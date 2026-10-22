import { Brand } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="relative flex min-h-screen items-center justify-center px-4 py-10">
      <div className="absolute top-3 right-3">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center text-2xl">
          <Brand />
        </div>
        <div className="card glow-box p-6">{children}</div>
      </div>
    </main>
  );
}
