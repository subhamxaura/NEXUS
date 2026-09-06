export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

const TOKEN_KEY = "nexus_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${apiBase()}${path}`, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string> ?? {}) } });
  if (res.status === 401) {
    clearToken();
    throw new ApiError(401, "Session expired. Sign in again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* keep status text */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export interface Repo {
  id: number;
  owner: string;
  name: string;
  default_branch: string;
  last_analyzed_sha: string | null;
}

export interface Analysis {
  id: number;
  commit_sha: string;
  status: string;
  health_score: number | null;
  metrics: {
    health_breakdown?: Record<string, number>;
    availability?: Record<string, string>;
    skipped?: string[];
    file_count?: number;
    finding_count?: number;
    risk_contributors?: Record<string, Record<string, number>>;
  };
  analyzer_version: string;
  cache_hit: boolean;
}

export interface Finding {
  id: number;
  type: string;
  severity: string;
  path: string;
  line: number | null;
  message: string;
  rule_id: string;
  evidence: Record<string, unknown>;
  priority_score: number;
}

export interface FileMetric {
  path: string;
  language: string;
  loc: number;
  complexity: number;
  maintainability: number | null;
  churn: number;
  test_presence: number;
  risk_score: number;
  in_degree: number;
  out_degree: number;
  risk_contributors: Record<string, number>;
}

export interface Graph {
  nodes: { path: string; risk: number }[];
  edges: { src: string; dst: string; kind: string }[];
}

export const login = (loginName: string) =>
  api<{ token: string; login: string }>("/api/v1/auth/dev-login", {
    method: "POST",
    body: JSON.stringify({ login: loginName })
  });

export const listRepos = () => api<Repo[]>("/api/v1/repos");
export const connectRepo = (owner: string, name: string) =>
  api<Repo>("/api/v1/repos", { method: "POST", body: JSON.stringify({ owner, name }) });
export const analyzeRepo = (id: number) => api<Analysis>(`/api/v1/repos/${id}/analyze`, { method: "POST" });
export const latestAnalysis = (id: number) => api<Analysis>(`/api/v1/repos/${id}/analysis/latest`);
export const listFindings = (id: number) => api<Finding[]>(`/api/v1/repos/${id}/findings`);
export const listFiles = (id: number) => api<FileMetric[]>(`/api/v1/repos/${id}/files`);
export const repoGraph = (id: number) => api<Graph>(`/api/v1/repos/${id}/graph`);
export const readFile = (id: number, path: string) =>
  api<{ path: string; content: string }>(`/api/v1/repos/${id}/files/${path}`);

export interface PlanStep {
  agent: string;
  depends_on: string[];
}

export interface Mission {
  id: number;
  repo_id: number;
  goal: string;
  finding_id: number | null;
  status: string;
  plan: { goal: string; finding_id: number | null; steps: PlanStep[] };
  result: Record<string, unknown>;
}

export interface AgentTask {
  id: number;
  agent_name: string;
  status: string;
  dependencies: string[];
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  token_usage: { model: string; prompt_tokens: number; completion_tokens: number };
  duration_ms: number;
  attempt_count: number;
  model: string;
  prompt_version: string;
  error: string | null;
}

export interface MissionEvent {
  id: number;
  task_id: number | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Patch {
  id: number;
  diff: string;
  files_changed: string[];
  rationale: string;
  applied_state: string;
}

export interface MissionDetail {
  mission: Mission;
  tasks: AgentTask[];
  patch: Patch | null;
}

export const startMission = (repoId: number, goal: string, findingId?: number) =>
  api<Mission>(`/api/v1/repos/${repoId}/missions`, {
    method: "POST",
    body: JSON.stringify({ goal, finding_id: findingId ?? null })
  });
export const listMissions = (repoId: number) => api<Mission[]>(`/api/v1/repos/${repoId}/missions`);
export const missionDetail = (id: number) => api<MissionDetail>(`/api/v1/missions/${id}`);
export const missionEvents = (id: number) => api<MissionEvent[]>(`/api/v1/missions/${id}/events`);
export const cancelMission = (id: number) => api<Mission>(`/api/v1/missions/${id}/cancel`, { method: "POST" });
