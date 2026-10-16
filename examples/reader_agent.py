"""Run from the repository: python3 examples/reader_agent.py [project-root]."""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from oopc.graph import Graph
from oopc.trace import TraceStore
from oopc.util import resolve_release

root=Path(sys.argv[1] if len(sys.argv)>1 else ".").resolve()
release=resolve_release(root)
run=TraceStore(root).create(release,"Example reader agent · scoped polyethylene evidence")
graph=Graph(release,trace=run,agent_id="example-reader")
polymer=graph.get("wop-000001")
graph.traverse(polymer["@id"],predicate="narrower",direction="out")
section=graph.get("section:wop-000001:mechanicalProperties")
evidence=graph.evidence(section["@id"])
run.artifact({"title":"Located source-backed seed material",
              "answer":"The record contains a mechanical-property section with source locators. Its scientific claims remain seed drafts.",
              "claims":[{"id":"answer-1","text":"Mechanical-property evidence records were returned.",
                         "citations":[record["@id"] for record in evidence["records"]]}]},"example-reader")
run.finish()
print("Open Task replay in the inspector and select",run.path.name)
