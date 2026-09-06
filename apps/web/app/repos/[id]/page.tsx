"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { Providers } from "../../providers";
import {
  ApiError,
  latestAnalysis,
  listFiles,
  listFindings,
  listMissions,
  readFile,
  repoGraph,
  startMission,
  type FileMetric,
  type Finding
} from "@/lib/api";
import { useRouter } from "next/navigation";

type Tab = "overview" | "explorer" | "findings" | "graph" | "missions";

const SEV_COLOR: Record<string, string> = {
  critical: "text-red-300 border-red-900",
  high: "text-orange-300 border-orange-900",
  medium: "text-amber-300 border-amber-900",
  low: "text-sky-300 border-sky-900",
  info: "text-zinc-400 border-zinc-800"
};

function FindingRow({ f }: { f: Finding }) {
  const color = SEV_COLOR[f.severity] ?? SEV_COLOR["info"];
  return (
    <li className="rounded-lg border border-zinc-800 bg-zinc-950 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full border px-2 py-0.5 text-xs ${color}`}>{f.severity}</span>
        <span className="font-mono text-xs text-zinc-300">
          {f.path}
          {f.line ? `:${f.line}` : ""}
        </span>
        <span className="ml-auto font-mono text-xs text-zinc-500">priority {f.priority_score.toFixed(3)}</span>
      </div>
      <p className="mt-1.5 text-sm text-zinc-200">{f.message}</p>
      <p className="mt-1 font-mono text-xs text-zinc-500">
        {f.type} · {f.rule_id}
      </p>
    </li>
  );
}

function FileRow({ m, onOpen }: { m: FileMetric; onOpen: (path: string) => void }) {
  const contrib = Object.entries(m.risk_contributors)
    .map(([k, v]) => `${k} ${v.toFixed(2)}`)
    .join(" · ");
  return (
    <tr className="border-t border-zinc-800/60 hover:bg-zinc-900/40">
      <td className="px-3 py-2 font-mono text-xs">
        <button className="hover:underline" onClick={() => onOpen(m.path)} title={m.path}>
          {m.path}
        </button>
      </td>
      <td className="px-3 py-2 text-xs text-zinc-400">{m.language}</td>
      <td className="px-3 py-2 text-right font-mono text-xs">{m.loc}</td>
      <td className="px-3 py-2 text-right font-mono text-xs">{m.complexity % 1 === 0 ? m.complexity : m.complexity.toFixed(1)}</td>
      <td className="px-3 py-2 text-right font-mono text-xs">{m.churn}</td>
      <td className="px-3 py-2 text-right font-mono text-xs" title={contrib || "no breakdown"}>
        {m.risk_score.toFixed(2)}
      </td>
    </tr>
  );
}

function RepoInner({ id }: { id: number }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [preview, setPreview] = useState<string | null>(null);

  const analysis = useQuery({ queryKey: ["analysis", id], queryFn: () => latestAnalysis(id), retry: false });
  const findings = useQuery({ queryKey: ["findings", id], queryFn: () => listFindings(id), enabled: analysis.isSuccess, retry: false });
  const files = useQuery({ queryKey: ["files", id], queryFn: () => listFiles(id), enabled: analysis.isSuccess, retry: false });
  const graph = useQuery({ queryKey: ["graph", id], queryFn: () => repoGraph(id), enabled: tab === "graph", retry: false });
  const previewQ = useQuery({
    queryKey: ["file", id, preview],
    queryFn: () => readFile(id, preview ?? ""),
    enabled: preview !== null,
    retry: false
  });

  const breakdown = analysis.data?.metrics.health_breakdown ?? {};
  const availability = analysis.data?.metrics.availability ?? {};
  const skipped = analysis.data?.metrics.skipped ?? [];
  const dependentsOf = (path: string) => graph.data?.edges.filter((e) => e.dst === path).map((e) => e.src) ?? [];

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <Link href="/" className="text-xs text-zinc-400 hover:underline">
        ← Dashboard
      </Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Repository #{id}</h1>
        {analysis.data && (
          <span className="font-mono text-xs text-zinc-500" title={analysis.data.commit_sha}>
            {analysis.data.commit_sha.slice(0, 12)} · {analysis.data.analyzer_version} · {analysis.data.status}
          </span>
        )}
      </div>

      {analysis.isLoading ? (
        <div className="mt-6 h-40 animate-pulse rounded-xl border border-zinc-800 bg-zinc-950" aria-label="Loading analysis" />
      ) : analysis.isError ? (
        <div role="alert" className="mt-6 rounded-xl border border-zinc-800 bg-zinc-950 p-8 text-center">
          <p className="text-sm font-medium">No analysis yet</p>
          <p className="mt-2 text-sm text-zinc-400">
            {(analysis.error as ApiError).message === "Not Found" || (analysis.error as Error).message.includes("404")
              ? "Run Analyze from the dashboard, then reload."
              : (analysis.error as Error).message}
          </p>
        </div>
      ) : (
        <>
          <nav className="mt-6 flex gap-1 border-b border-zinc-800" aria-label="Repository sections">
            {(["overview", "explorer", "findings", "graph", "missions"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                aria-current={tab === t ? "page" : undefined}
                className={`px-4 py-2 text-sm capitalize ${tab === t ? "border-b-2 border-zinc-100 font-medium" : "text-zinc-400 hover:text-zinc-200"}`}
              >
                {t}
                {t === "findings" && findings.data ? ` (${findings.data.length})` : ""}
              </button>
            ))}
          </nav>

          {tab === "overview" && analysis.data && (
            <section className="mt-6 grid gap-4 md:grid-cols-2">
              <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-6">
                <p className="text-xs uppercase tracking-wide text-zinc-500">Health score</p>
                <p className="mt-2 text-5xl font-semibold">{analysis.data.health_score?.toFixed(0) ?? "—"}</p>
                <div className="mt-4 space-y-2">
                  {Object.entries(breakdown).map(([k, v]) => (
                    <div key={k}>
                      <div className="flex justify-between text-xs text-zinc-400">
                        <span className="capitalize">{k}</span>
                        <span className="font-mono">−{v}</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded bg-zinc-800">
                        <div className="h-1.5 rounded bg-zinc-400" style={{ width: `${Math.min(100, (v / 35) * 100)}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
                {Object.keys(breakdown).length === 0 && <p className="mt-2 text-sm text-zinc-400">No files analyzed.</p>}
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-6">
                <p className="text-xs uppercase tracking-wide text-zinc-500">Analysis state</p>
                <dl className="mt-3 space-y-1.5 font-mono text-xs">
                  <div className="flex justify-between"><dt className="text-zinc-500">files</dt><dd>{String(analysis.data.metrics.file_count ?? "—")}</dd></div>
                  <div className="flex justify-between"><dt className="text-zinc-500">findings</dt><dd>{String(analysis.data.metrics.finding_count ?? "—")}</dd></div>
                  <div className="flex justify-between"><dt className="text-zinc-500">status</dt><dd>{analysis.data.status}</dd></div>
                </dl>
                {analysis.data.status === "partial" && (
                  <p className="mt-3 rounded-md border border-amber-900 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
                    Partial analysis: some files were skipped or unparseable. {skipped.length > 0 && `Skipped: ${skipped.slice(0, 5).join(", ")}${skipped.length > 5 ? ` (+${skipped.length - 5} more)` : ""}.`}
                  </p>
                )}
                <p className="mt-3 text-xs uppercase tracking-wide text-zinc-500">Analyzer availability</p>
                <ul className="mt-1.5 space-y-1 font-mono text-xs">
                  {Object.entries(availability).map(([k, v]) => (
                    <li key={k} className="flex justify-between gap-4">
                      <span className="text-zinc-400">{k}</span>
                      <span className={v === "available" ? "text-emerald-300" : "text-zinc-500"}>{v}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          {tab === "explorer" && (
            <section className="mt-6 grid gap-4 lg:grid-cols-2">
              <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-950">
                {files.isLoading ? (
                  <div className="h-40 animate-pulse" aria-label="Loading files" />
                ) : (
                  <table className="w-full text-left">
                    <thead>
                      <tr className="text-xs text-zinc-500">
                        <th className="px-3 py-2 font-medium">Path</th>
                        <th className="px-3 py-2 font-medium">Lang</th>
                        <th className="px-3 py-2 text-right font-medium">LOC</th>
                        <th className="px-3 py-2 text-right font-medium">CC</th>
                        <th className="px-3 py-2 text-right font-medium">Churn</th>
                        <th className="px-3 py-2 text-right font-medium" title="w1·complexity + w2·churn + w3·centrality + w4·security + w5·(1−tests)">Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {files.data?.map((m) => (
                        <FileRow key={m.path} m={m} onOpen={setPreview} />
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="px-3 py-2 text-xs text-zinc-500">Hover a risk score for its contributors.</p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
                {preview === null ? (
                  <p className="text-sm text-zinc-500">Select a file to preview its analyzed snapshot.</p>
                ) : previewQ.isLoading ? (
                  <div className="h-40 animate-pulse" aria-label="Loading file" />
                ) : previewQ.isError ? (
                  <p role="alert" className="text-sm text-red-300">Could not load file: {(previewQ.error as Error).message}</p>
                ) : (
                  <>
                    <div className="flex items-center justify-between">
                      <p className="font-mono text-xs text-zinc-300">{previewQ.data?.path}</p>
                      <button className="text-xs text-zinc-500 hover:text-zinc-200" onClick={() => setPreview(null)}>Close</button>
                    </div>
                    <pre className="mt-3 max-h-[32rem] overflow-auto rounded bg-black/40 p-3 font-mono text-xs leading-relaxed text-zinc-200">
                      {previewQ.data?.content}
                    </pre>
                  </>
                )}
              </div>
            </section>
          )}

          {tab === "findings" && (
            <section className="mt-6">
              {findings.isLoading ? (
                <div className="h-40 animate-pulse rounded-xl border border-zinc-800 bg-zinc-950" aria-label="Loading findings" />
              ) : findings.data?.length === 0 ? (
                <p className="rounded-xl border border-zinc-800 bg-zinc-950 p-8 text-center text-sm text-zinc-400">
                  No findings. Either the code is clean or analyzers were unavailable — check the Overview availability list.
                </p>
              ) : (
                <ul className="space-y-2">
                  {findings.data?.map((f) => (
                    <FindingRow key={f.id} f={f} />
                  ))}
                </ul>
              )}
            </section>
          )}

          {tab === "graph" && (
            <section className="mt-6 rounded-xl border border-zinc-800 bg-zinc-950 p-6">
              {graph.isLoading ? (
                <div className="h-40 animate-pulse" aria-label="Loading graph" />
              ) : graph.data?.edges.length === 0 ? (
                <p className="text-sm text-zinc-400">No intra-repository imports detected.</p>
              ) : (
                <>
                  <p className="text-xs text-zinc-500">
                    {graph.data?.nodes.length} files · {graph.data?.edges.length} import edges. Select a file to highlight its dependents.
                  </p>
                  <ul className="mt-4 space-y-1.5">
                    {graph.data?.edges.map((e, i) => (
                      <li key={i} className="font-mono text-xs">
                        <button className="text-sky-300 hover:underline" onClick={() => setPreview(e.src)} title="Preview source">{e.src}</button>
                        <span className="text-zinc-500"> → </span>
                        <button className="text-zinc-200 hover:underline" onClick={() => setPreview(e.dst)} title="Preview target">{e.dst}</button>
                      </li>
                    ))}
                  </ul>
                  {preview !== null && graph.data && (
                    <div className="mt-4 rounded-md border border-zinc-800 p-3">
                      <p className="font-mono text-xs text-zinc-300">{preview}</p>
                      <p className="mt-1 text-xs text-zinc-500">
                        Dependents ({dependentsOf(preview).length}): {dependentsOf(preview).join(", ") || "none"}
                      </p>
                      <button className="mt-2 text-xs text-zinc-500 hover:text-zinc-200" onClick={() => setPreview(null)}>Clear</button>
                    </div>
                  )}
                </>
              )}
              {previewQ.data && tab === "graph" && preview !== null && (
                <pre className="mt-4 max-h-80 overflow-auto rounded bg-black/40 p-3 font-mono text-xs text-zinc-200">{previewQ.data.content}</pre>
              )}
            </section>
          )}

          {tab === "missions" && (
            <MissionsTab
              repoId={id}
              findings={findings.data ?? []}
              ready={analysis.isSuccess}
            />
          )}
        </>
      )}
    </main>
  );
}

function MissionsTab({ repoId, findings, ready }: { repoId: number; findings: Finding[]; ready: boolean }) {
  const router = useRouter();
  const [goal, setGoal] = useState("");
  const [findingId, setFindingId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const missions = useQuery({ queryKey: ["missions", repoId], queryFn: () => listMissions(repoId), retry: false });

  const start = async () => {
    if (!goal.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const m = await startMission(repoId, goal.trim(), findingId ? Number(findingId) : undefined);
      router.push(`/missions/${m.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Mission failed to start");
      setBusy(false);
    }
  };

  if (!ready) return <p className="mt-6 text-sm text-zinc-400">Analyze the repository first.</p>;
  return (
    <section className="mt-6 grid gap-4 lg:grid-cols-2">
      <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-6">
        <h2 className="text-sm font-medium">Start a mission</h2>
        <label className="mt-4 block text-xs text-zinc-400" htmlFor="mission-goal">
          Goal
        </label>
        <textarea
          id="mission-goal"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Fix the highest-risk issue."
          rows={3}
          className="mt-1 w-full rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-600"
        />
        <label className="mt-3 block text-xs text-zinc-400" htmlFor="mission-finding">
          Finding (optional)
        </label>
        <select
          id="mission-finding"
          value={findingId}
          onChange={(e) => setFindingId(e.target.value)}
          className="mt-1 w-full rounded-md border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm"
        >
          <option value="">None — general goal</option>
          {findings.slice(0, 50).map((f) => (
            <option key={f.id} value={f.id}>
              #{f.id} [{f.severity}] {f.rule_id} — {f.path}
            </option>
          ))}
        </select>
        {error && <p role="alert" className="mt-3 text-sm text-red-300">{error}</p>}
        <button
          onClick={start}
          disabled={busy || !goal.trim()}
          className="mt-4 rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-white disabled:opacity-40"
        >
          {busy ? "Running agents… (this takes a while)" : "Start mission"}
        </button>
        <p className="mt-2 text-xs text-zinc-500">
          Runs Scout → Architect → Security → Coder with a real model. Produces a reviewable diff only — no pushes.
        </p>
      </div>
      <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-6">
        <h2 className="text-sm font-medium">Mission history</h2>
        {missions.isLoading ? (
          <div className="mt-3 h-24 animate-pulse" aria-label="Loading missions" />
        ) : missions.data?.length === 0 ? (
          <p className="mt-3 text-sm text-zinc-500">No missions yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {missions.data?.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-3 rounded-lg border border-zinc-800 px-3 py-2">
                <div className="min-w-0">
                  <Link href={`/missions/${m.id}`} className="block truncate text-sm hover:underline">
                    #{m.id} — {m.goal}
                  </Link>
                  <span className="font-mono text-xs text-zinc-500">{m.status}</span>
                </div>
                <Link href={`/missions/${m.id}`} className="shrink-0 text-xs text-zinc-300 hover:underline">
                  Open
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <Providers>
      <RepoInner id={Number(id)} />
    </Providers>
  );
}
