import pytest

from tools.kg_render import GraphError, apply_views, load_graph, main, render_views

G = """schema_version: 1
updated: 2026-11-15
nodes:
  - {id: a, type: component, label: "Caller TTS + cache"}
  - {id: b, type: external, label: "OpenRouter :free"}
  - {id: d, type: decision, label: 'D3 HMS = "hospital" (mgmt)'}
  - {id: m0, type: milestone, label: "M0 Foundations"}
edges:
  - {from: a, to: b, rel: depends_on}
  - {from: a, to: d, rel: decided_by}
  - {from: a, to: m0, rel: delivered_in}
"""


def write(p, text):
    p.write_text(text, encoding="utf-8")
    return p


def markers(*names):
    return "".join(f"<!-- kg:begin {n} -->\nold\n<!-- kg:end {n} -->\n" for n in names)


ALL_MARKERS = markers("pipeline", "governance", "milestones")


def test_duplicate_id_rejected(tmp_path):
    with pytest.raises(GraphError, match="duplicate"):
        load_graph(write(tmp_path / "g.yaml", G.replace("id: b,", "id: a,")))


def test_dangling_edge_rejected(tmp_path):
    with pytest.raises(GraphError, match="unknown node"):
        load_graph(write(tmp_path / "g.yaml", G.replace("to: b,", "to: zz,")))


def test_unknown_rel_rejected(tmp_path):
    with pytest.raises(GraphError):
        load_graph(write(tmp_path / "g.yaml", G.replace("rel: depends_on", "rel: likes")))


def test_unknown_type_rejected(tmp_path):
    with pytest.raises(GraphError):
        load_graph(write(tmp_path / "g.yaml", G.replace("type: external", "type: gadget")))


def test_labels_with_special_chars_are_quoted(tmp_path):
    views = render_views(load_graph(write(tmp_path / "g.yaml", G)))
    assert 'a["Caller TTS + cache"]' in views["pipeline"]
    assert 'b{{"OpenRouter :free"}}' in views["pipeline"]
    assert "#quot;hospital#quot;" in views["governance"]


def test_views_filter_by_type(tmp_path):
    views = render_views(load_graph(write(tmp_path / "g.yaml", G)))
    assert views["pipeline"].startswith("flowchart")
    assert "d[/" not in views["pipeline"]
    assert "d[/" in views["governance"]
    assert "m0((" in views["milestones"] and "a[" in views["milestones"]


def test_render_is_deterministic(tmp_path):
    g = load_graph(write(tmp_path / "g.yaml", G))
    assert render_views(g) == render_views(g)


def test_apply_views_replaces_only_marked_blocks():
    readme = "intro\n<!-- kg:begin pipeline -->\nold\n<!-- kg:end pipeline -->\ntail\n"
    out = apply_views(readme, {"pipeline": "flowchart LR\n  x", "governance": "flowchart TB"})
    assert out.startswith("intro\n<!-- kg:begin pipeline -->\n```mermaid\nflowchart LR\n  x\n```\n")
    assert out.endswith("<!-- kg:end pipeline -->\ntail\n")
    assert "governance" not in out


def test_check_detects_drift_and_write_fixes_it(tmp_path):
    d = tmp_path / "dir with space"
    d.mkdir()
    gp = write(d / "g.yaml", G)
    rp = write(d / "README.md", "x\n" + ALL_MARKERS)
    assert main(["--check", "--graph", str(gp), "--readme", str(rp)]) == 1
    assert main(["--graph", str(gp), "--readme", str(rp)]) == 0
    assert main(["--check", "--graph", str(gp), "--readme", str(rp)]) == 0


@pytest.mark.parametrize(
    "readme",
    [
        "no markers at all\n",
        markers("pipeline", "governance"),
        ALL_MARKERS.replace("<!-- kg:end governance -->", "<!-- kg:end governanc -->"),
        ALL_MARKERS + markers("pipeline"),
        "<!-- kg:end pipeline -->\n<!-- kg:begin pipeline -->\n"
        + markers("governance", "milestones"),
    ],
    ids=["none", "one-view-missing", "typo-in-end", "duplicate", "end-before-begin"],
)
@pytest.mark.parametrize("check", [True, False], ids=["check", "write"])
def test_missing_or_broken_markers_rejected(tmp_path, capsys, readme, check):
    gp = write(tmp_path / "g.yaml", G)
    rp = write(tmp_path / "README.md", readme)
    args = (["--check"] if check else []) + ["--graph", str(gp), "--readme", str(rp)]
    assert main(args) == 2
    assert "marker" in capsys.readouterr().err
    assert rp.read_text(encoding="utf-8") == readme
