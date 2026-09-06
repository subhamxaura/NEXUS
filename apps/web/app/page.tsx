"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Providers } from "./providers";
import {
  ApiError,
  analyzeRepo,
  apiBase,
  clearToken,
  connectRepo,
  getToken,
  listRepos,
  login,
  setToken
} from "@/lib/api";

function HealthBadge({ score }: { score: number | null }) {
  if (score === null || score === undefined)
    return <span className="text-xs text-zinc-500">not analyzed</span>;
  const color = score >= 75 ? "text-emerald-300 border-emerald-900" : score >= 50 ? "text-amber-300 border-amber-900" : "text-red-300 border-red-900";
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${color}`}>
      {score.toFixed(0)}
    </span>
  );
}

function DashboardInner() {
  const qc = useQueryClient();
  const [authed, setAuthed] = useState(() => getToken() !== null);
  const [owner, setOwner] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState<number | null>(null);

  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const r = await fetch(`${apiBase()}/api/v1/health`);
      if (!r.ok) throw new Error(`API ${r.status}`);
      return (await r.json()) as { status: string; analyzer_version: string };
    },
    retry: 1
  });

  const repos = useQuery({
    queryKey: ["repos"],
    queryFn: listRepos,
    enabled: authed,
    retry: false
  });

  const doLogin = async () => {
    setError(null);
    try {
      const res = await login("developer");
      setToken(res.token);
      setAuthed(true);
      void qc.invalidateQueries({ queryKey: ["repos"] });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Login failed. Is the API running?");
    }
  };

  const connect = useMutation({
    mutationFn: () => connectRepo(owner.trim(), name.trim()),
    onSuccess: () => {
      setOwner("");
      setName("");
      setError(null);
      void qc.invalidateQueries({ queryKey: ["repos"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Connect failed")
  });

  const analyze = async (id: number) => {
    setAnalyzing(id);
    setError(null);
    try {
      await analyzeRepo(id);
      void qc.invalidateQueries({ queryKey: ["repos"] });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(null);
    }
  };

  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">NEXUS</h1>
          <p className="mt-1 text-sm text-zinc-400">Engineering command center</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="rounded-full border border-zinc-800 px-3 py-1 text-xs text-zinc-300" aria-live="polite">
            {health.isLoading ? "Checking API…" : health.isError ? "API unreachable" : `API ${health.data?.status} · ${health.data?.analyzer_version}`}
          </span>
          {authed ? (
            <button
              className="rounded-md border border-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-900"
              onClick={() => {
                clearToken();
                setAuthed(false);
              }}
            >
              Sign out
            </button>
          ) : (
            <button className="rounded-md bg-zinc-100 px-3 py-1.5 text-xs font-medium text-zinc-900 hover:bg-white" onClick={doLogin}>
              Sign in (dev)
            </button>
          )}
        </div>
      </header>

      {error && (
        <div role="alert" className="mt-6 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {!authed ? (
        <section className="mt-10 rounded-xl border border-zinc-800 bg-zinc-950 p-8 text-center">
          <h2 className="text-lg font-medium">Sign in to connect repositories</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-zinc-400">
            Development sign-in is enabled because GitHub OAuth is not configured. No demo data is
            shown until you connect a real public repository.
          </p>
        </section>
      ) : (
        <>
          <section className="mt-10 rounded-xl border border-zinc-800 bg-zinc-950 p-6">
            <h2 className="text-sm font-medium text-zinc-200">Connect a public repository</h2>
            <form
              className="mt-4 flex flex-col gap-3 sm:flex-row"
              onSubmit={(e) => {
                e.preventDefault();
                if (owner.trim() && name.trim()) connect.mutate();
              }}
            >
              <input
                aria-label="Owner"
                placeholder="owner (e.g. psf)"
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                className="flex-1 rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-600"
              />
              <input
                aria-label="Repository name"
                placeholder="repo (e.g. requests)"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="flex-1 rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-600"
              />
              <button
                type="submit"
                disabled={connect.isPending || !owner.trim() || !name.trim()}
                className="rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-white disabled:opacity-40"
              >
                {connect.isPending ? "Connecting…" : "Connect"}
              </button>
            </form>
          </section>

          <section className="mt-6">
            <h2 className="text-sm font-medium text-zinc-200">Repositories</h2>
            {repos.isLoading ? (
              <div className="mt-3 space-y-2" aria-label="Loading">
                {[0, 1].map((i) => (
                  <div key={i} className="h-16 animate-pulse rounded-lg border border-zinc-800 bg-zinc-950" />
                ))}
              </div>
            ) : repos.isError ? (
              <p className="mt-3 text-sm text-zinc-400">Could not load repositories. Is the API running?</p>
            ) : repos.data?.length === 0 ? (
              <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950 p-8 text-center">
                <p className="text-sm font-medium">No repositories connected</p>
                <p className="mx-auto mt-2 max-w-md text-sm text-zinc-400">
                  Connect a real public repository above. NEXUS never shows fake repositories or findings.
                </p>
              </div>
            ) : (
              <ul className="mt-3 space-y-2">
                {repos.data?.map((r) => (
                  <li key={r.id} className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950 px-4 py-3">
                    <div className="flex items-center gap-3">
                      <Link href={`/repos/${r.id}`} className="text-sm font-medium hover:underline">
                        {r.owner}/{r.name}
                      </Link>
                      {r.last_analyzed_sha ? (
                        <span className="font-mono text-xs text-zinc-500">{r.last_analyzed_sha.slice(0, 7)}</span>
                      ) : (
                        <span className="text-xs text-zinc-500">never analyzed</span>
                      )}
                    </div>
                    <button
                      onClick={() => void analyze(r.id)}
                      disabled={analyzing === r.id}
                      className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-900 disabled:opacity-40"
                    >
                      {analyzing === r.id ? "Analyzing…" : r.last_analyzed_sha ? "Re-analyze" : "Analyze"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-zinc-500">
              Health scores appear on each repository page after analysis. <HealthBadge score={null} />
            </p>
          </section>
        </>
      )}
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
