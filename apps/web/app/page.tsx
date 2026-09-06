"use client";
import { useQuery } from "@tanstack/react-query";
import { Providers } from "./providers";
import { apiBase } from "@/lib/api";

function DashboardInner() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const r = await fetch(`${apiBase()}/api/v1/health`);
      if (!r.ok) throw new Error(`API ${r.status}`);
      return (await r.json()) as { status: string; analyzer_version: string };
    },
    retry: 1
  });

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">NEXUS</h1>
          <p className="mt-1 text-sm text-zinc-400">Engineering command center · Phase 0 foundation</p>
        </div>
        <span className="rounded-full border border-zinc-800 px-3 py-1 text-xs text-zinc-300" aria-live="polite">
          {isLoading ? "Checking API…" : isError ? "API unreachable" : `API ${data?.status} · ${data?.analyzer_version}`}
        </span>
      </header>

      <section className="mt-10 rounded-xl border border-zinc-800 bg-zinc-950 p-8 text-center">
        <h2 className="text-lg font-medium">No repositories connected</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-zinc-400">
          Repository import and analysis arrive in Phase 1. This empty state is intentional — NEXUS never shows fake
          repositories or findings.
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <button disabled className="cursor-not-allowed rounded-md bg-zinc-800 px-4 py-2 text-sm text-zinc-500" title="Available in Phase 1">
            Analyze repository
          </button>
          <button disabled className="cursor-not-allowed rounded-md border border-zinc-800 px-4 py-2 text-sm text-zinc-500" title="Available in Phase 2">
            Start mission
          </button>
        </div>
      </section>
    </main>
  );
}

export default function Page() {
  return (
    <Providers>
      <DashboardInner />
    </Providers>
  );
}
