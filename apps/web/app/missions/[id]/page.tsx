"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { Providers } from "../../providers";
import {
  approveMission,
  cancelMission,
  missionDetail,
  missionEvents,
  type AgentTask,
  type MissionEvent,
  type ValidationRun
} from "@/lib/api";

const TASK_DOT: Record<string, string> = {
  completed: "bg-emerald-400",
  running: "bg-sky-400 animate-pulse",
  failed: "bg-red-400",
  blocked: "bg-amber-400",
  pending: "bg-zinc-600"
};

function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="max-h-[28rem] overflow-auto rounded bg-black/40 p-3 font-mono text-xs leading-relaxed">
      {diff.split("\n").map((line, i) => (
        <div
          key={i}
          className={
            line.startsWith("+") && !line.startsWith("+++")
              ? "bg-emerald-950/60 text-emerald-200"
              : line.startsWith("-") && !line.startsWith("---")
                ? "bg-red-950/60 text-red-200"
                : line.startsWith("@@")
                  ? "text-sky-300"
                  : "text-zinc-300"
          }
        >
          {line || " "}
        </div>
      ))}
    </pre>
  );
}

function TaskRow({ task }: { task: AgentTask }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-lg border border-zinc-800 bg-zinc-950 px-4 py-3">
      <button className="flex w-full items-center gap-3 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className={`h-2.5 w-2.5 rounded-full ${TASK_DOT[task.status] ?? "bg-zinc-600"}`} aria-hidden />
        <span className="font-mono text-sm capitalize">{task.agent_name}</span>
        <span className="text-xs text-zinc-500">{task.status}</span>
        <span className="ml-auto font-mono text-xs text-zinc-500">
          {task.prompt_version} · {task.attempt_count} attempt{task.attempt_count === 1 ? "" : "s"} ·{" "}
          {(task.duration_ms / 1000).toFixed(1)}s
          {(task.token_usage.prompt_tokens + task.token_usage.completion_tokens) > 0 &&
            ` · ${task.token_usage.prompt_tokens + task.token_usage.completion_tokens} tokens`}
        </span>
      </button>
      {task.error && <p className="mt-2 text-xs text-red-300">{task.error}</p>}
      {open && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div>
            <p className="text-xs uppercase tracking-wide text-zinc-500">Input</p>
            <pre className="mt-1 max-h-56 overflow-auto rounded bg-black/40 p-2 font-mono text-xs text-zinc-300">
              {JSON.stringify(task.input, null, 2)}
            </pre>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-zinc-500">Output</p>
            <pre className="mt-1 max-h-56 overflow-auto rounded bg-black/40 p-2 font-mono text-xs text-zinc-300">
              {task.output && Object.keys(task.output).length > 0 ? JSON.stringify(task.output, null, 2) : "(none)"}
            </pre>
          </div>
        </div>
      )}
    </li>
  );
}

function EventStream({ events }: { events: MissionEvent[] | undefined }) {
  if (!events || events.length === 0) return <p className="text-xs text-zinc-500">No events yet.</p>;
  return (
    <ol className="max-h-72 space-y-1 overflow-auto font-mono text-xs">
      {events.map((e) => (
        <li key={e.id} className="flex gap-2 text-zinc-400">
          <span className="text-zinc-600">#{e.id}</span>
          <span className={e.event_type === "failed" || e.event_type === "blocked" ? "text-red-300" : e.event_type === "completed" || e.event_type === "mission_completed" ? "text-emerald-300" : "text-zinc-200"}>
            {e.event_type}
          </span>
          <span className="truncate text-zinc-500">{JSON.stringify(e.payload)}</span>
        </li>
      ))}
    </ol>
  );
}

function ControlInner({ id }: { id: number }) {
  const [error, setError] = useState<string | null>(null);
  const detail = useQuery({ queryKey: ["mission", id], queryFn: () => missionDetail(id), refetchInterval: 3000 });
  const events = useQuery({ queryKey: ["mission-events", id], queryFn: () => missionEvents(id), refetchInterval: 2000 });

  const mission = detail.data?.mission;
  const active = mission && ["created", "running", "validating", "reviewing"].includes(mission.status);
  const [token, setToken] = useState("");
  const [approving, setApproving] = useState(false);

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <Link href={mission ? `/repos/${mission.repo_id}` : "/"} className="text-xs text-zinc-400 hover:underline">
        ← Back
      </Link>
      {detail.isLoading ? (
        <div className="mt-4 h-40 animate-pulse rounded-xl border border-zinc-800 bg-zinc-950" aria-label="Loading mission" />
      ) : detail.isError || !mission ? (
        <p role="alert" className="mt-4 text-sm text-red-300">Could not load mission.</p>
      ) : (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold">Mission #{mission.id}</h1>
            <span className="rounded-full border border-zinc-700 px-2.5 py-0.5 text-xs">{mission.status.replaceAll("_", " ")}</span>
            {active && (
              <button
                className="rounded-md border border-zinc-700 px-3 py-1 text-xs hover:bg-zinc-900"
                onClick={() => {
                  setError(null);
                  cancelMission(id)
                    .then(() => detail.refetch())
                    .catch((e: Error) => setError(e.message));
                }}
              >
                Cancel
              </button>
            )}
          </div>
          <p className="mt-2 max-w-3xl text-sm text-zinc-300">{mission.goal}</p>
          {mission.finding_id && <p className="mt-1 font-mono text-xs text-zinc-500">from finding #{mission.finding_id}</p>}
          {error && <p role="alert" className="mt-3 text-sm text-red-300">{error}</p>}

          {mission.status === "needs_human" && (
            <div className="mt-4 rounded-md border border-amber-900 bg-amber-950/30 px-4 py-3 text-sm text-amber-200" role="alert">
              Needs a human: {String(mission.result.reason ?? "see trace below")}.
              {mission.result.detail ? ` ${String(mission.result.detail).slice(0, 300)}` : ""} No PR was created.
            </div>
          )}
          {mission.status === "failed" && (
            <div className="mt-4 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-200" role="alert">
              Mission failed: {String(mission.result.detail ?? mission.result.reason ?? "unknown")}. No PR was created.
            </div>
          )}

          <div className="mt-6 grid gap-4 lg:grid-cols-5">
            <section className="lg:col-span-3">
              <h2 className="text-sm font-medium text-zinc-200">Plan & tasks</h2>
              <ol className="mt-1 font-mono text-xs text-zinc-500">
                {mission.plan.steps?.map((s, i) => (
                  <li key={i}>
                    {i + 1}. {s.agent}
                    {s.depends_on.length > 0 && <span> (after {s.depends_on.join(", ")})</span>}
                  </li>
                ))}
              </ol>
              <ul className="mt-3 space-y-2">
                {detail.data?.tasks.map((t) => (
                  <TaskRow key={t.id} task={t} />
                ))}
              </ul>
            </section>
            <section className="lg:col-span-2">
              <h2 className="text-sm font-medium text-zinc-200">Live event stream</h2>
              <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950 p-3">
                <EventStream events={events.data} />
              </div>
            </section>
          </div>

          {detail.data?.patch && (
            <section className="mt-6">
              <h2 className="text-sm font-medium text-zinc-200">
                Proposed patch <span className="font-mono text-xs text-zinc-500">({detail.data.patch.applied_state})</span>
              </h2>
              <p className="mt-1 font-mono text-xs text-zinc-500">
                {detail.data.patch.files_changed.join(", ")} · {String(detail.data.mission.result.diff_check ?? "")}
              </p>
              <p className="mt-2 max-w-3xl text-sm text-zinc-300">{detail.data.patch.rationale}</p>
              <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950 p-3">
                <DiffView diff={detail.data.patch.diff} />
              </div>
              <p className="mt-2 text-xs text-zinc-500">
                Validation runs in an isolated Docker sandbox; nothing below has been pushed anywhere.
              </p>
            </section>
          )}

          {detail.data && detail.data.validation_runs.length > 0 && (
            <section className="mt-6">
              <h2 className="text-sm font-medium text-zinc-200">Sandbox validation</h2>
              <ul className="mt-3 space-y-2">
                {detail.data.validation_runs.map((run) => (
                  <ValidationRow key={run.id} run={run} />
                ))}
              </ul>
            </section>
          )}

          {detail.data?.review && (
            <section className="mt-6 rounded-xl border border-zinc-800 bg-zinc-950 p-6">
              <h2 className="text-sm font-medium text-zinc-200">Independent review</h2>
              <div className="mt-2 flex items-center gap-3">
                <span
                  className={`rounded-full border px-2.5 py-0.5 text-xs ${
                    detail.data.review.verdict === "approve"
                      ? "border-emerald-900 text-emerald-300"
                      : "border-red-900 text-red-300"
                  }`}
                >
                  {detail.data.review.verdict === "approve" ? "approved" : "changes requested"}
                </span>
                <span className="font-mono text-xs text-zinc-400">score {detail.data.review.score}/100</span>
                <span className="font-mono text-xs text-zinc-600" title={detail.data.review.diff_hash}>
                  diff {detail.data.review.diff_hash.slice(0, 12)}
                </span>
              </div>
              {detail.data.review.comments.length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-zinc-300">
                  {detail.data.review.comments.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              )}
              {detail.data.review.concerns.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-red-200">
                  {detail.data.review.concerns.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {mission.status === "awaiting_approval" && !detail.data?.pull_request && (
            <section className="mt-6 rounded-xl border border-emerald-900 bg-emerald-950/20 p-6">
              <h2 className="text-sm font-medium text-emerald-100">Human approval required</h2>
              <p className="mt-1 text-sm text-zinc-300">
                Validation passed and the independent reviewer approved. Nothing has been pushed —
                approving creates branch <span className="font-mono text-xs">nexus/{mission.id}-…</span> and
                opens a pull request. This is the only action that touches GitHub.
              </p>
              <label className="mt-4 block text-xs text-zinc-400" htmlFor="gh-token">
                GitHub token (PAT with contents:write + pull_requests:write; never stored)
              </label>
              <input
                id="gh-token"
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="github_pat_…"
                autoComplete="off"
                className="mt-1 w-full max-w-md rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono text-sm outline-none focus:border-emerald-700"
              />
              <div>
                <button
                  disabled={approving || !token.trim()}
                  onClick={() => {
                    setApproving(true);
                    setError(null);
                    approveMission(id, token.trim())
                      .then(() => {
                        setToken("");
                        void detail.refetch();
                      })
                      .catch((e: Error) => setError(e.message))
                      .finally(() => setApproving(false));
                  }}
                  className="mt-3 rounded-md bg-emerald-200 px-4 py-2 text-sm font-medium text-emerald-950 hover:bg-emerald-100 disabled:opacity-40"
                >
                  {approving ? "Creating PR…" : "Approve & open pull request"}
                </button>
              </div>
            </section>
          )}

          {detail.data?.pull_request && (
            <section className="mt-6 rounded-xl border border-zinc-800 bg-zinc-950 p-6">
              <h2 className="text-sm font-medium text-zinc-200">Pull request</h2>
              <p className="mt-2 font-mono text-xs text-zinc-400">
                #{detail.data.pull_request.pr_number} · {detail.data.pull_request.branch} →{" "}
                {detail.data.pull_request.base} · {detail.data.pull_request.state}
              </p>
              <a
                href={detail.data.pull_request.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-sm text-sky-300 hover:underline"
              >
                {detail.data.pull_request.url}
              </a>
            </section>
          )}
        </>
      )}
    </main>
  );
}

function ValidationRow({ run }: { run: ValidationRun }) {
  const [open, setOpen] = useState(false);
  const color =
    run.status === "passed" ? "text-emerald-300" : run.status === "failed" ? "text-red-300" : "text-amber-300";
  return (
    <li className="rounded-lg border border-zinc-800 bg-zinc-950 px-4 py-3">
      <button className="flex w-full flex-wrap items-center gap-2 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className={`font-mono text-xs ${color}`}>{run.status}</span>
        <span className="font-mono text-xs text-zinc-200">{run.command}</span>
        <span className="ml-auto font-mono text-xs text-zinc-500">
          exit {run.exit_code ?? "?"} · {run.duration_s.toFixed(1)}s · {run.sandbox_id}
        </span>
      </button>
      {open && (
        <pre className="mt-2 max-h-64 overflow-auto rounded bg-black/40 p-2 font-mono text-xs text-zinc-300">
          {run.log_tail || "(no output)"}
        </pre>
      )}
    </li>
  );
}

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <Providers>
      <ControlInner id={Number(id)} />
    </Providers>
  );
}
