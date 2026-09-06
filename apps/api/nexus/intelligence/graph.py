"""Dependency graph (NetworkX): degrees, centrality, strongly connected components."""

import networkx as nx


def build_graph(nodes: list[str], edges: list[tuple[str, str]]) -> nx.DiGraph:
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(sorted(nodes))
    graph.add_edges_from(sorted(set(edges)))
    return graph


def degrees(graph: nx.DiGraph) -> dict[str, tuple[int, int]]:
    return {n: (graph.in_degree(n), graph.out_degree(n)) for n in graph.nodes}


def centrality(graph: nx.DiGraph) -> dict[str, float]:
    """Normalized in-degree centrality in [0, 1]. 0 for trivial graphs."""
    n = graph.number_of_nodes()
    if n <= 1:
        return {node: 0.0 for node in graph.nodes}
    return {node: graph.in_degree(node) / (n - 1) for node in graph.nodes}


def strongly_connected(graph: nx.DiGraph) -> list[list[str]]:
    return [sorted(comp) for comp in nx.strongly_connected_components(graph) if len(comp) > 1]


def dependents(graph: nx.DiGraph, path: str, depth: int = 3) -> set[str]:
    """Reverse-reachable nodes within `depth` hops (bounded impact analysis)."""
    seen: set[str] = set()
    frontier = {path}
    for _ in range(depth):
        nxt: set[str] = set()
        for node in frontier:
            if node in graph:
                nxt.update(graph.predecessors(node))
        nxt -= seen
        seen |= nxt
        frontier = nxt
        if not frontier:
            break
    return seen
