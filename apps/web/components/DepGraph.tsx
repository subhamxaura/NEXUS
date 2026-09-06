"use client";
import { useMemo, useState } from "react";

export interface GraphNode {
  path: string;
  risk: number;
}

export interface GraphEdge {
  src: string;
  dst: string;
  kind: string;
}

interface Positioned {
  path: string;
  risk: number;
  x: number;
  y: number;
  layer: number;
}

const LAYER_W = 240;
const ROW_H = 54;
const NODE_W = 210;
const NODE_H = 34;
const PAD = 40;

/** Deterministic layered layout: roots (no incoming edges) left, dependents flow right. */
export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]): Positioned[] {
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  for (const n of nodes) {
    incoming.set(n.path, 0);
    outgoing.set(n.path, []);
  }
  for (const e of edges) {
    if (!incoming.has(e.src) || !incoming.has(e.dst)) continue;
    incoming.set(e.dst, (incoming.get(e.dst) ?? 0) + 1);
    outgoing.get(e.src)?.push(e.dst);
  }
  const depth = new Map<string, number>();
  const visit = (path: string, seen: Set<string>): number => {
    const cached = depth.get(path);
    if (cached !== undefined) return cached;
    if (seen.has(path)) return 0; // cycle guard
    seen.add(path);
    let d = 0;
    for (const [src, dsts] of outgoing) {
      if (dsts.includes(path)) d = Math.max(d, visit(src, seen) + 1);
    }
    seen.delete(path);
    depth.set(path, d);
    return d;
  };
  for (const n of nodes) visit(n.path, new Set());
  const layers = new Map<number, Positioned[]>();
  const sorted = [...nodes].sort((a, b) =>
    (depth.get(a.path) ?? 0) - (depth.get(b.path) ?? 0) || a.path.localeCompare(b.path)
  );
  for (const n of sorted) {
    const layer = depth.get(n.path) ?? 0;
    const row = layers.get(layer) ?? [];
    row.push({
      path: n.path,
      risk: n.risk,
      layer,
      x: PAD + layer * LAYER_W,
      y: PAD + row.length * ROW_H
    });
    layers.set(layer, row);
  }
  return [...layers.values()].flat();
}

function riskColor(risk: number): string {
  if (risk >= 0.5) return "#f87171";
  if (risk >= 0.3) return "#fbbf24";
  return "#71717a";
}

export default function DepGraph({
  nodes,
  edges,
  selected,
  onSelect
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selected: string | null;
  onSelect: (path: string | null) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [filter, setFilter] = useState<"all" | "risky" | "connected">("all");

  const positioned = useMemo(() => layoutGraph(nodes, edges), [nodes, edges]);
  const byPath = useMemo(() => new Map(positioned.map((p) => [p.path, p])), [positioned]);

  const related = useMemo(() => {
    if (!selected) return null;
    const set = new Set<string>([selected]);
    for (const e of edges) {
      if (e.src === selected) set.add(e.dst);
      if (e.dst === selected) set.add(e.src);
    }
    return set;
  }, [selected, edges]);

  const visible = positioned.filter((p) => {
    if (filter === "risky") return p.risk >= 0.3;
    if (filter === "connected") return !related || related.has(p.path);
    return true;
  });
  const visibleSet = useMemo(() => new Set(visible.map((p) => p.path)), [visible]);
  const visibleEdges = edges.filter((e) => visibleSet.has(e.src) && visibleSet.has(e.dst));

  const width = Math.max(...positioned.map((p) => p.x), 0) + NODE_W + PAD * 2;
  const height = Math.max(...positioned.map((p) => p.y), 0) + NODE_H + PAD;
  const vbW = width / zoom;
  const vbH = height / zoom;

  const basename = (p: string) => p.split("/").pop() ?? p;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Graph controls">
        {(["all", "risky", "connected"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            aria-pressed={filter === f}
            className={`rounded-md border px-2.5 py-1 text-xs capitalize ${
              filter === f ? "border-zinc-400 bg-zinc-800" : "border-zinc-800 text-zinc-400"
            }`}
          >
            {f === "all" ? "All files" : f === "risky" ? "Risk ≥ 0.30" : "Connected to selection"}
          </button>
        ))}
        <div className="ml-auto flex gap-1">
          <button aria-label="Zoom out" className="rounded-md border border-zinc-800 px-2 py-1 text-xs" onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.2).toFixed(2)))}>−</button>
          <button aria-label="Zoom in" className="rounded-md border border-zinc-800 px-2 py-1 text-xs" onClick={() => setZoom((z) => Math.min(2.5, +(z + 0.2).toFixed(2)))}>+</button>
          <button
            className="rounded-md border border-zinc-800 px-2 py-1 text-xs"
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
              onSelect(null);
            }}
          >
            Reset
          </button>
        </div>
      </div>
      <svg
        viewBox={`${-pan.x} ${-pan.y} ${vbW} ${vbH}`}
        className="mt-3 w-full rounded-lg border border-zinc-800 bg-black/30"
        style={{ minHeight: 320 }}
        role="img"
        aria-label={`Dependency graph: ${visible.length} files, ${visibleEdges.length} imports`}
        tabIndex={0}
        onKeyDown={(e) => {
          const step = 40 / zoom;
          if (e.key === "ArrowLeft") setPan((p) => ({ ...p, x: p.x - step }));
          if (e.key === "ArrowRight") setPan((p) => ({ ...p, x: p.x + step }));
          if (e.key === "ArrowUp") setPan((p) => ({ ...p, y: p.y - step }));
          if (e.key === "ArrowDown") setPan((p) => ({ ...p, y: p.y + step }));
          if (e.key === "Escape") onSelect(null);
        }}
      >
        {visibleEdges.map((e, i) => {
          const a = byPath.get(e.src);
          const b = byPath.get(e.dst);
          if (!a || !b) return null;
          const active = !selected || e.src === selected || e.dst === selected;
          const x1 = a.x + NODE_W;
          const y1 = a.y + NODE_H / 2;
          const x2 = b.x;
          const y2 = b.y + NODE_H / 2;
          const mx = (x1 + x2) / 2;
          return (
            <path
              key={i}
              d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
              fill="none"
              stroke={active ? "#52525b" : "#27272a"}
              strokeWidth={e.src === selected || e.dst === selected ? 2 : 1.2}
              markerEnd="url(#arrow)"
            />
          );
        })}
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M 0 0 L 8 4 L 0 8" fill="none" stroke="#52525b" strokeWidth="1.2" />
          </marker>
        </defs>
        {visible.map((p) => {
          const dimmed = related && !related.has(p.path);
          const isSel = selected === p.path;
          return (
            <g
              key={p.path}
              opacity={dimmed ? 0.25 : 1}
              onClick={() => onSelect(isSel ? null : p.path)}
              style={{ cursor: "pointer" }}
            >
              <title>{`${p.path} · risk ${p.risk.toFixed(2)}`}</title>
              <rect
                x={p.x}
                y={p.y}
                width={NODE_W}
                height={NODE_H}
                rx={7}
                fill={isSel ? "#27272a" : "#09090b"}
                stroke={isSel ? "#e4e4e7" : riskColor(p.risk)}
                strokeWidth={isSel ? 2 : 1.4}
              />
              <circle cx={p.x + 14} cy={p.y + NODE_H / 2} r={5} fill={riskColor(p.risk)} />
              <text x={p.x + 26} y={p.y + NODE_H / 2 + 4.5} fill="#e4e4e7" fontSize={12} fontFamily="monospace">
                {basename(p.path).length > 26 ? `${basename(p.path).slice(0, 25)}…` : basename(p.path)}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="mt-1 text-xs text-zinc-500">
        Click a node to highlight its imports and dependents. Arrow keys pan when focused; Esc clears.
        Full paths in the list below.
      </p>
    </div>
  );
}
