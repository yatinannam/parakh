"""Render Mermaid views of the Parakh knowledge graph.

Usage:
    python -m tools.kg_render            rewrite the generated blocks in docs/kg/README.md
    python -m tools.kg_render --check    exit 1 if docs/kg/README.md is out of date
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

NodeType = Literal["constraint", "component", "external", "decision", "risk", "doc", "milestone"]
Rel = Literal[
    "depends_on",
    "calls",
    "produces",
    "consumes",
    "constrained_by",
    "decided_by",
    "mitigates",
    "documented_in",
    "delivered_in",
    "compatible_with",
]

DEFAULT_GRAPH = Path("docs/kg/graph.yaml")
DEFAULT_README = Path("docs/kg/README.md")

_SHAPES: dict[str, tuple[str, str]] = {
    "component": ('["', '"]'),
    "external": ('{{"', '"}}'),
    "constraint": ('(["', '"])'),
    "decision": ('[/"', '"/]'),
    "risk": ('>"', '"]'),
    "doc": ('[("', '")]'),
    "milestone": ('(("', '"))'),
}
_GOVERNANCE_TYPES = {"constraint", "decision", "risk"}


class GraphError(ValueError):
    """The knowledge graph file is invalid."""


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    label: str
    summary: str = ""
    path: str | None = None
    by: str | None = None


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    rel: Rel


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    updated: str
    nodes: list[Node]
    edges: list[Edge]


def load_graph(path: Path) -> Graph:
    """Load and validate a graph file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "updated" in raw:
        raw["updated"] = str(raw["updated"])
    try:
        graph = Graph.model_validate(raw)
    except ValidationError as exc:
        raise GraphError(f"{path}: {exc}") from exc
    seen: set[str] = set()
    for node in graph.nodes:
        if node.id in seen:
            raise GraphError(f"{path}: duplicate node id {node.id!r}")
        seen.add(node.id)
    for edge in graph.edges:
        for end in (edge.from_, edge.to):
            if end not in seen:
                raise GraphError(
                    f"{path}: edge {edge.from_}->{edge.to} references unknown node {end!r}"
                )
    return graph


def _node_line(node: Node) -> str:
    left, right = _SHAPES[node.type]
    label = node.label.replace('"', "#quot;")
    return f"{node.id}{left}{label}{right}"


def _edge_line(edge: Edge) -> str:
    return f"  {edge.from_} -->|{edge.rel}| {edge.to}"


def _sorted_edges(edges: list[Edge]) -> list[Edge]:
    return sorted(edges, key=lambda e: (e.from_, e.to, e.rel))


def _flowchart(direction: str, nodes: list[Node], edges: list[Edge]) -> str:
    lines = [f"flowchart {direction}"]
    lines += [f"  {_node_line(n)}" for n in sorted(nodes, key=lambda n: n.id)]
    lines += [_edge_line(e) for e in _sorted_edges(edges)]
    return "\n".join(lines)


def _pipeline(graph: Graph) -> str:
    keep = {n.id for n in graph.nodes if n.type in {"component", "external"}}
    nodes = [n for n in graph.nodes if n.id in keep]
    edges = [e for e in graph.edges if e.from_ in keep and e.to in keep]
    return _flowchart("LR", nodes, edges)


def _governance(graph: Graph) -> str:
    by_id = {n.id: n for n in graph.nodes}
    gov = {n.id for n in graph.nodes if n.type in _GOVERNANCE_TYPES}
    edges = [e for e in graph.edges if e.from_ in gov or e.to in gov]
    keep = set(gov) | {e.from_ for e in edges} | {e.to for e in edges}
    return _flowchart("TB", [by_id[i] for i in keep], edges)


def _milestones(graph: Graph) -> str:
    by_id = {n.id: n for n in graph.nodes}
    milestones = sorted((n for n in graph.nodes if n.type == "milestone"), key=lambda n: n.id)
    members: dict[str, list[str]] = {m.id: [] for m in milestones}
    placed: set[str] = set()
    for edge in _sorted_edges(graph.edges):
        if edge.rel == "delivered_in" and edge.to in members and edge.from_ not in placed:
            members[edge.to].append(edge.from_)
            placed.add(edge.from_)
    lines = ["flowchart LR"]
    for m in milestones:
        lines.append(f'  subgraph g_{m.id}[" "]')
        lines.append(f"    {_node_line(m)}")
        lines += [f"    {_node_line(by_id[i])}" for i in sorted(members[m.id])]
        lines.append("  end")
    ms = set(members)
    lines += [_edge_line(e) for e in _sorted_edges(graph.edges) if e.from_ in ms and e.to in ms]
    return "\n".join(lines)


def render_views(graph: Graph) -> dict[str, str]:
    """Return Mermaid flowcharts keyed by view name."""
    return {
        "pipeline": _pipeline(graph),
        "governance": _governance(graph),
        "milestones": _milestones(graph),
    }


def apply_views(readme_text: str, views: dict[str, str]) -> str:
    """Replace each marked block in the README with its rendered view."""
    out = readme_text
    for name, body in views.items():
        pattern = re.compile(
            rf"(<!-- kg:begin {re.escape(name)} -->\n).*?(<!-- kg:end {re.escape(name)} -->)",
            re.DOTALL,
        )
        block = f"```mermaid\n{body}\n```\n"
        out = pattern.sub(lambda m, b=block: m.group(1) + b + m.group(2), out)
    return out


def marker_problems(readme_text: str, names: list[str]) -> list[str]:
    """Describe each view whose begin/end marker pair is missing, repeated or reversed."""
    problems = []
    for name in names:
        begin = f"<!-- kg:begin {name} -->"
        end = f"<!-- kg:end {name} -->"
        n_begin, n_end = readme_text.count(begin), readme_text.count(end)
        if n_begin != 1 or n_end != 1:
            problems.append(f"view {name!r}: expected one {begin} and one {end}")
        elif readme_text.index(begin) > readme_text.index(end):
            problems.append(f"view {name!r}: end marker comes before begin marker")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.kg_render")
    parser.add_argument("--check", action="store_true", help="fail if the README is out of date")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        graph = load_graph(args.graph)
    except GraphError as exc:
        print(exc, file=sys.stderr)
        return 2
    current = args.readme.read_text(encoding="utf-8")
    views = render_views(graph)
    problems = marker_problems(current, list(views))
    if problems:
        for problem in problems:
            print(f"{args.readme}: {problem}", file=sys.stderr)
        return 2
    updated = apply_views(current, views)
    if args.check:
        if updated != current:
            print(f"{args.readme} is out of date; run python -m tools.kg_render", file=sys.stderr)
            return 1
        return 0
    args.readme.write_bytes(updated.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
