"""Command line: the graph reader, traces, the app, and the core loop."""
import argparse
import json
import os
import shutil
import signal
import sys
import time
import uuid
from pathlib import Path

from .util import atomic_json, read_json, resolve_release


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def deposit_outcome(task):
    """One line on what happened to an answer's findings, for `oopc ask`."""
    state, deposit = task.get("depositState") or {}, task.get("deposit") or {}
    if state.get("status") == "saved":
        return "Findings saved: %d findings and %d source notes (%d already known)." % (
            deposit.get("findings") or 0, deposit.get("notes") or 0, deposit.get("duplicates") or 0)
    if state.get("status") == "failed":
        return "Findings not saved (%s): %s. The answer stands." % (
            state.get("reason"), (state.get("message") or "no detail").rstrip(". "))
    return "Findings are still being saved."


def publish_records(root, records, ontology, metadata):
    from .release import build_release, verify_release
    releases = Path(root) / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    staging = releases / (".assembly-" + uuid.uuid4().hex)
    try:
        build_release(staging, records, ontology, metadata)
        manifest = verify_release(staging)
        target = releases / manifest["release_id"]
        if target.exists():
            verify_release(target)
            shutil.rmtree(staging)
        else:
            staging.rename(target)
        atomic_json(releases / "current.json", {"release_id": manifest["release_id"]})
        return target
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def demo(root, release, delay=0):
    from .graph import Graph
    from .trace import TraceStore
    run = TraceStore(root).create(release, "Seed exploration · polyethylene evidence", task={
        "question": "Locate the polyethylene family, narrower materials and mechanical-property evidence.",
        "notice": "Recorded reader demonstration, not a model run or a reviewed scientific result."})
    g = Graph(release, run, "reader-demo")
    emit({"run_id": run.path.name, "status": "running"})
    g.get("wop-000001")
    time.sleep(delay)
    g.search("high density polyethylene", type="PolymerConcept", limit=3)
    time.sleep(delay)
    g.traverse("wop-000001", predicate="narrower", direction="out")
    time.sleep(delay)
    chosen = g.get("section:wop-000001:mechanicalProperties")
    evidence = g.evidence(chosen["@id"])
    if evidence["records"]:
        g.get(evidence["records"][0]["@id"])
    run.artifact({"title": "Evidence located", "answer": "The seed contains scoped mechanical-property prose and linked source locators. These keep seed status; this demonstration reviews nothing.",
                  "claims": [{"id": "location-1", "text": "Mechanical-property section and supporting source records located.",
                              "citations": [chosen["@id"]] + [r["@id"] for r in evidence["records"][:2]]}]}, "reader-demo")
    run.finish()
    return {"run_id": run.path.name, "status": "completed", "events": run.events()["last_sequence"]}


def parser():
    p = argparse.ArgumentParser(prog="oopc", description="Open Ontology of Polymer Chemistry")
    p.add_argument("--root", default=os.environ.get("OOPC_ROOT", "."), help="Project directory (private state stays under .oopc)")
    p.add_argument("--release", help="Release ID or directory; defaults to the current release")
    sub = p.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("import-seed", help="Build and select an immutable release from the wiki v2 snapshot")
    seed.add_argument("snapshot")
    seed.add_argument("--expected-sha256", help="Required source digest; defaults to config/seed-lock.json when present")
    sub.add_parser("verify", help="Verify release checksums and record contracts")
    inspect = sub.add_parser("inspect", help="Open the researcher app and the operator inspector")
    inspect.add_argument("--port", type=int, default=8765)
    inspect.add_argument("--open", action="store_true")
    inspect.add_argument("--replay-only", action="store_true", help="Inspect imported runs without a graph release")

    search = sub.add_parser("search", help="Search the graph")
    search.add_argument("query", nargs="?", default="")
    for key in ("type", "status", "layer", "predicate", "property", "process", "application", "environment", "source", "facet"):
        search.add_argument("--" + key)
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--offset", type=int, default=0)
    for name in ("get", "evidence"):
        sub.add_parser(name).add_argument("id")
    sub.add_parser("vocabulary").add_argument("--term")
    traverse = sub.add_parser("traverse")
    traverse.add_argument("id")
    traverse.add_argument("--depth", type=int, default=1)
    traverse.add_argument("--direction", choices=["in", "out", "both"], default="both")
    for key in ("predicate", "layer", "status"):
        traverse.add_argument("--" + key)
    traverse.add_argument("--limit", type=int, default=150)
    claims = sub.add_parser("claims")
    for key in ("subject", "predicate", "object", "layer", "status"):
        claims.add_argument("--" + key)
    claims.add_argument("--limit", type=int, default=100)
    for name in ("search", "get", "evidence", "vocabulary", "traverse", "claims"):
        s = sub.choices[name]
        s.add_argument("--run")
        s.add_argument("--agent", default="cli-agent")
        s.add_argument("--parent-event")
    mcp = sub.add_parser("mcp", help="Serve instrumented graph tools over MCP stdio")
    mcp.add_argument("--run")
    mcp.add_argument("--agent", default="mcp-agent")

    start = sub.add_parser("run-start")
    start.add_argument("title")
    start.add_argument("--task")
    sub.add_parser("run-list")
    events = sub.add_parser("run-events")
    events.add_argument("run_id")
    events.add_argument("--after", type=int, default=0)
    finish = sub.add_parser("run-finish")
    finish.add_argument("run_id")
    finish.add_argument("--status", default="completed", choices=["completed", "failed", "cancelled", "paused"])
    artifact = sub.add_parser("run-artifact")
    artifact.add_argument("run_id")
    artifact.add_argument("file")
    artifact.add_argument("--agent", default="adapter")
    delivery = sub.add_parser("run-delivery")
    delivery.add_argument("run_id")
    delivery.add_argument("event_id")
    delivery.add_argument("model_call_id")
    delivery.add_argument("ids", nargs="+")
    delivery.add_argument("--representation", default="content", choices=["content", "reference", "summary"])
    export = sub.add_parser("export-replay")
    export.add_argument("run_id")
    export.add_argument("output")
    sub.add_parser("import-replay").add_argument("bundle")
    otel = sub.add_parser("export-otel")
    otel.add_argument("run_id")
    otel.add_argument("output")
    sub.add_parser("demo").add_argument("--delay", type=float, default=0)
    diff = sub.add_parser("diff")
    diff.add_argument("before")
    diff.add_argument("after")

    ask = sub.add_parser("ask", help="Ask one question with your subscription and wait for the answer")
    ask.add_argument("question")
    ask.add_argument("--seconds", type=int, choices=[300, 600, 1200], default=600)
    ask.add_argument("--engine", choices=["codex", "claude-code"])
    sub.add_parser("questions", help="List recent questions")
    knowledge = sub.add_parser("knowledge", help="Knowledge summary, or findings by status")
    knowledge.add_argument("--status", choices=["supported", "accepted", "unreviewed", "uncertain", "unsupported"])
    knowledge.add_argument("--limit", type=int, default=20)
    knowledge.add_argument("--export", metavar="FOLDER",
                           help="Write a public snapshot (findings and source notes; no questions, traces or excerpts)")
    knowledge.add_argument("--import", dest="import_snapshot", metavar="FOLDER",
                           help="Start this workspace's empty knowledge store from a public snapshot")
    research = sub.add_parser("research", help="Add a question to the research queue")
    research.add_argument("question")
    loop = sub.add_parser("loop", help="Run or schedule the background loop")
    ls = loop.add_subparsers(dest="loop_action", required=True)
    ls.add_parser("tick", help="Review what is waiting, then work the research queue once")
    ls.add_parser("status")
    ls.add_parser("install", help="Run the loop hourly with launchd")
    ls.add_parser("uninstall")
    reflect = sub.add_parser("reflect", help="Replay recorded searches and fix the names, polymer ids and property "
                                             "terms search reads (optional; off by default)")
    rs = reflect.add_subparsers(dest="reflect_action", required=True)
    q = rs.add_parser("run", help="Run once now (uses your subscription)")
    q.add_argument("--dry-run", action="store_true", help="Mine and show the dossier only: no engine, nothing written")
    rs.add_parser("status", help="The edits in force, the reverted ones and recent runs")
    q = rs.add_parser("revert", help="Undo edits in force by id")
    q.add_argument("edits", nargs="+")
    q = rs.add_parser("schedule", help="Run from the loop's tick every DAYS days (0 turns it off)")
    q.add_argument("days", type=int)
    parity = sub.add_parser("parity", help="Compare the researcher with a plain web session on the fixed parity set")
    ps = parity.add_subparsers(dest="parity_action", required=True)
    q = ps.add_parser("run", help="Answer and check the parity set on one engine (uses your subscription)")
    q.add_argument("--engine", choices=["codex", "claude-code"], required=True)
    q.add_argument("--checker", choices=["codex", "claude-code"], help="Engine for the answer checks; defaults to --engine")
    q.add_argument("--only", choices=["covered", "uncovered"])
    q.add_argument("--canaries", action="store_true", help="Also review the canaries (after changing the reviewer)")
    q = ps.add_parser("recheck", help="Fill in failed checks of a run without answering again")
    q.add_argument("--all-checks", action="store_true", help="Reassess every stored answer and preserve previous checks")
    q.add_argument("run", nargs="?")
    q.add_argument("--checker", choices=["codex", "claude-code"], required=True)
    q = ps.add_parser("report", help="The latest (or a named) parity report")
    q.add_argument("run", nargs="?")
    ps.add_parser("runs")
    q = ps.add_parser("compare", help="Two runs side by side, e.g. before and after a change to the researcher")
    q.add_argument("baseline")
    q.add_argument("trial")
    q = ps.add_parser("canaries", help="Only the reviewer canaries, on one engine")
    q.add_argument("--engine", choices=["codex", "claude-code"], required=True)
    improve = sub.add_parser("improve", help="This week's loop summary")
    im = improve.add_subparsers(dest="improve_action", required=True)
    im.add_parser("summary")
    upkeep = sub.add_parser("upkeep", help="One-off store cleanups before a freeze (a report unless --apply)")
    upkeep.add_argument("action", choices=["audit", "requeue", "excerpts", "titles", "polymers", "disambiguate", "duplicates",
                                           "index", "reviews"])
    upkeep.add_argument("--apply", action="store_true", help="Change the store (after a backup copy)")
    upkeep.add_argument("--capture", action="store_true", help="disambiguate: fetch sources not captured yet")
    upkeep.add_argument("--crossref-cache", metavar="FOLDER", help="titles: Crossref responses another tool cached")
    upkeep.add_argument("--corrections", metavar="FILE", help="polymers: approved finding-id-to-polymer-id corrections")
    upkeep.add_argument("--limit", type=int, default=10, help="reviews: how many answers' waiting findings to review")
    legacy = sub.add_parser("import-legacy", help="Import useful knowledge from the 0.11 workflow (preview unless --apply)")
    legacy.add_argument("--apply", action="store_true")
    legacy.add_argument("--rewrite-statements", action="store_true",
                        help="Reword imported label-like statements as sentences (one writer call, one check call)")
    legacy.add_argument("--writer", choices=["codex", "claude-code"], default="claude-code")
    legacy.add_argument("--checker", choices=["codex", "claude-code"], default="codex")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    root = Path(args.root).resolve()
    command = args.command
    try:
        from .trace import TraceStore, import_replay
        store = TraceStore(root)
        if command == "import-seed":
            from .seed import import_seed
            lock = root / "config" / "seed-lock.json"
            expected = args.expected_sha256 or (read_json(lock)["sha256"] if lock.exists() else None)
            records, ontology, metadata = import_seed(args.snapshot, expected)
            path = publish_records(root, records, ontology, metadata)
            return emit({"release": str(path), "manifest": read_json(path / "manifest.json")["counts"]})
        if command == "run-list":
            return emit({"runs": store.list()})
        if command == "run-events":
            return emit(store.run(args.run_id).events(args.after))
        if command == "run-finish":
            return emit(store.run(args.run_id).finish(args.status))
        if command == "run-artifact":
            return emit(store.run(args.run_id).artifact(read_json(args.file), args.agent))
        if command == "run-delivery":
            return emit(store.run(args.run_id).delivery(args.event_id, args.ids, args.model_call_id, args.representation))
        if command == "export-replay":
            return emit(store.run(args.run_id).export(args.output))
        if command == "import-replay":
            return emit(import_replay(args.bundle, store))
        if command == "export-otel":
            from .otel import export_spans
            atomic_json(args.output, export_spans(store.run(args.run_id)), private=True)
            return emit({"path": str(Path(args.output).resolve()), "notice": "Local OTLP JSON; no network telemetry was sent."})
        if command == "diff":
            from .graph import release_diff
            return emit(release_diff(resolve_release(root, args.before), resolve_release(root, args.after)))
        if command == "ask":
            from .ask import Questions
            service = Questions(root)
            view = service.submit({"question": args.question, "budgetSeconds": args.seconds, "authorizeSubscription": True,
                                   **({"runtime": args.engine} if args.engine else {})})
            service.wait()
            answered = service.get(view["id"])
            emit(answered)
            sys.stdout.flush()
            if (answered.get("depositState") or {}).get("status") == "saving":
                print("Saving the findings and source notes this answer read…", file=sys.stderr, flush=True)
            service.wait(reviews=True)  # The answer is already out; let its findings be saved and reviewed.
            if answered.get("depositState"):
                print(deposit_outcome(service.get(view["id"])), file=sys.stderr, flush=True)
            return
        if command == "questions":
            from .ask import Questions
            return emit(Questions(root).list())
        if command == "knowledge":
            from . import knowledge
            if args.export:
                return emit(knowledge.export(root, args.export))
            if args.import_snapshot:
                return emit(knowledge.import_snapshot(root, args.import_snapshot))
            if args.status:
                return emit({"findings": knowledge.recent(root, args.status, args.limit)})
            return emit(knowledge.summary(root))
        if command == "research":
            from .loop import add_research
            return emit(add_research(root, args.question))
        if command == "loop":
            from . import loop
            if args.loop_action == "tick":
                return emit(loop.tick(root))
            if args.loop_action == "status":
                return emit(loop.status(root))
            if args.loop_action == "install":
                return emit(loop.install(root))
            return emit(loop.uninstall())
        if command == "reflect":
            from . import loop, reflect
            if args.reflect_action == "run":
                return emit(reflect.run(root, dry_run=args.dry_run,
                                        progress=lambda m: print("reflect: " + m, file=sys.stderr, flush=True)))
            if args.reflect_action == "status":
                return emit(reflect.status(root))
            if args.reflect_action == "revert":
                return emit({"reverted": [reflect.revert(root, identifier) for identifier in args.edits]})
            return emit({"reflectEveryDays": loop.update_settings(root, {"reflectEveryDays": args.days})["reflectEveryDays"]})
        if command == "parity":
            from . import parity
            if args.parity_action == "run":
                return emit(parity.run(root, engine=args.engine, checker=args.checker, only=args.only, canaries=args.canaries,
                                       progress=lambda m: print("parity: " + m, file=sys.stderr, flush=True)))
            if args.parity_action == "recheck":
                return emit(parity.recheck(root, args.run, checker=args.checker, all_checks=args.all_checks,
                                           progress=lambda m: print("parity: " + m, file=sys.stderr, flush=True)))
            if args.parity_action == "report":
                return emit(parity.report(root, args.run))
            if args.parity_action == "runs":
                return emit({"runs": parity.runs(root)})
            if args.parity_action == "compare":
                from .improve import compare
                return emit(compare(parity.report(root, args.baseline), parity.report(root, args.trial)))
            from .engines import run_session
            return emit(parity.run_canaries(root, args.engine, runner=run_session))
        if command == "improve":
            from . import improve
            return emit(improve.summary(root))
        if command == "upkeep":
            from . import upkeep
            if args.action == "audit":
                return emit(upkeep.audit(root))
            if args.action == "reviews":
                from . import loop
                return emit({"reviews": loop.review_stage(root, limit=args.limit)})
            options = {"capture": args.capture} if args.action == "disambiguate" else (
                {"cache": args.crossref_cache} if args.action == "titles" else {})
            action = (lambda: upkeep.corrections(root, args.corrections, apply=args.apply)) if (
                args.action == "polymers" and args.corrections) else (
                lambda: upkeep.ACTIONS[args.action](root, apply=args.apply, **options))
            if not args.apply:
                return emit(action())
            from .knowledge import folder
            from .util import locked
            with locked(folder(root) / "review.lock"):  # Never change findings a review is reading.
                return emit(action())
        if command == "import-legacy":
            from .legacy_import import rewrite_statements, run
            if args.rewrite_statements:
                return emit(rewrite_statements(root, writer=args.writer, checker=args.checker, apply=args.apply))
            return emit(run(root, apply=args.apply))
        if command == "inspect" and args.replay_only:
            release = None
        else:
            try:
                release = resolve_release(root, args.release)
            except ValueError:
                if command == "inspect" and not args.release and store.list():
                    release = None
                else:
                    raise
        if command == "verify":
            from .release import verify_release
            m = verify_release(release)
            return emit({"valid": True, "release_id": m["release_id"], "counts": m["counts"]})
        if command == "inspect":
            from .server import make_server
            server = make_server(root, release, args.port)
            url = "http://127.0.0.1:" + str(server.server_port)
            print("OOPC app: " + url, flush=True)
            # A terminated app stops its running workers (engines' exit hook).
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
            if args.open:
                import webbrowser
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return
        if command == "run-start":
            run = store.create(release, args.title, task=read_json(args.task) if args.task else None)
            return emit({"run_id": run.path.name, "release_id": run.meta()["release_id"]})
        if command == "demo":
            return emit(demo(root, release, args.delay))
        if command == "mcp":
            from .mcp import MCP
            return MCP(root, release, args.run, args.agent).serve()
        from .graph import Graph
        trace = store.run(args.run) if getattr(args, "run", None) else None
        graph = Graph(release, trace, getattr(args, "agent", "cli-agent"))
        parent = getattr(args, "parent_event", None)
        if command == "get":
            return emit(graph.get(args.id, parent))
        if command == "evidence":
            return emit(graph.evidence(args.id, parent))
        if command == "vocabulary":
            return emit(graph.describe(args.term, parent))
        if command == "search":
            filters = {key: getattr(args, key) for key in ("type", "status", "layer", "predicate", "property", "process",
                                                           "application", "environment", "source", "facet") if getattr(args, key)}
            return emit(graph.search(args.query, args.limit, args.offset, parent_event_id=parent, **filters))
        if command == "traverse":
            return emit(graph.traverse(args.id, args.depth, args.direction, args.limit, parent_event_id=parent,
                                       **{k: getattr(args, k) for k in ("predicate", "layer", "status") if getattr(args, k)}))
        if command == "claims":
            return emit(graph.claims(args.subject, args.predicate, args.object, args.limit, parent_event_id=parent,
                                     **{k: getattr(args, k) for k in ("status", "layer") if getattr(args, k)}))
    except (ValueError, KeyError, FileNotFoundError, FileExistsError, RuntimeError) as error:
        print("oopc: " + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
