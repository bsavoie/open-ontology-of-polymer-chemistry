"""The shared driver of the Macromolecules case studies (pre-publication plan P1-13): questions × arms, one folder.

    import driver
    arms = [{"name": "P", "kind": "plain"},
            {"name": "K3", "kind": "researcher", "root": driver.workspace(BASE, "K3", releases=ROOT, store=K3)}]
    driver.prepare(BASE, "2026-11-example", questions, arms)  # the plan, fixed once written
    driver.run(BASE)                                          # resumable; a STOP file in BASE stops it at a boundary
    driver.report(BASE)                                       # report.json and report.md (run writes them too)

BASE is the experiment's private folder (`common.run_dir(name)`). An arm is one way of answering: `{"name", "kind":
"researcher" | "plain", "root", "web": True, "depth": "standard", "engine", "prompt"}`. A researcher arm answers as
`parity.answer_ontology` does, on a workspace whose store is a copy, and saves nothing to it (on code whose researcher
answers first and writes its findings in a second turn, from 2026-10-25, it runs through `parity.answer_ontology`,
the second turn recorded under the phase `study:<name>:<arm>:deposit`); a plain arm answers as
`parity.answer_direct`. A researcher arm's
optional `prompt` is the path of an instructions file used in place of the code's `ask.RESEARCHER` (the restarts'
evolved prompts, 2026-10-18): the plan records its version and `run` refuses if its text changed. Such a one-file
override is refused on two-part code (`ONE_FILE_ONLY`). The rules:

- Like for like (P0-4): question i is answered by every arm in turn, starting at arm i mod n, then all its answers
  are checked one right after the other by one checker engine; each answer and check records its UTC time and hour.
- Resumable: each (question, arm) item is saved atomically under `items/`; a rerun skips what is done and tries failed
  items again, and a question with a check missing has all its answers checked again together. A question stopped
  part-way whose answers are more than STALE old (a quota stop can last until a weekly reset) has all its arms
  answered again, the earlier answers kept as `previousAnswers`, so no question's arms are answered days apart.
- Named failures (P1-11): a timeout or a `RETRYABLE` failure is tried once more; quota, rate-limited and not-signed-in
  stop the run with that reason, as do the stop file and the deadline; any other failure is the item's. Once every
  question has been through, the questions with a failed item get one more pass after PASS_WAIT seconds; the run then
  ends completed, with what still failed counted (`failedItems` in state.json and the report).
- Sleep (P1-10): an attempt during which wall-clock time ran more than SLEPT seconds ahead of monotonic time slept
  (a closed lid) and is tried once more; the default Guard also stops a session as soon as the machine wakes.
- Cost (P1-12): every call goes through `calls.invoke` in the arm's workspace with phase
  `study:<name>:<arm>:research` or `:check`, and the report reads new tokens from that ledger.
"""
import datetime, functools, hashlib, json, re, shutil, sqlite3, statistics, threading, time
from collections import Counter
from pathlib import Path

import common  # puts the code under test first on sys.path, before any oopc import
from oopc import ask, calls, engines, knowledge, parity, reviewer  # noqa: E402
from oopc.trace import TraceStore  # noqa: E402
from oopc.util import atomic_bytes, atomic_json, now, private_sqlite, read_json, resolve_release  # noqa: E402

SLEPT = 60  # seconds that wall-clock time may run ahead of monotonic time before an attempt counts as slept
STOPS = ("quota", "rate-limited", "not-signed-in")  # Each stops the run; a rerun resumes it.
PASS_WAIT = 600  # seconds before the one more pass over the questions with failed items
STALE = 12 * 3600  # a question's answers older than this, with an arm still to answer, are all answered again
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
ONE_FILE_ONLY = ("An arm's own prompt file replaces one researcher prompt, but this code's researcher instructions have "
                 "two parts (ask.RESEARCHER answers, ask.DEPOSIT writes the findings in a second turn): a one-file "
                 "prompt override is not supported here. Run such an arm from a tag before 2026-10-25.")


def two_part():
    """Whether the code under study answers first and writes its findings in a second turn (2026-10-25 on)."""
    return hasattr(ask, "DEPOSIT")
COLUMNS = ("answered", "contradicted", "complete", "resultGiven", "passes", "accessUncertain", "tokens")


class Stop(Exception):
    """The run stops here, for the reason given; what is done stays done."""


def drift():
    """Wall-clock minus monotonic time: steady while the machine is awake, it grows by however long the machine slept,
    because the monotonic clock stops during sleep (mach_absolute_time on macOS, CLOCK_MONOTONIC on Linux)."""
    return time.time() - time.monotonic()


class Guard(common.Guard):
    """`common.Guard` whose watch loop (every 30 s) also stops a session the machine slept through: a closed lid then
    costs a retry rather than the rest of the session's time limit. Each calling thread's session keeps its own start
    (concurrent sessions share a guard: the restarts' research and audit worker), so one finishing never hides another's
    sleep. A session's own thread judges by its own start; any other thread (the guard's watch loops run in threads of
    their own, and a driver may poll) by every session running."""

    def __init__(self, *args, **options):
        super().__init__(*args, **options)
        self.sessions = {}  # calling thread -> drift() when its session started

    def __call__(self, engine, prompt, schema, **options):
        thread = threading.get_ident()
        self.sessions[thread] = drift()
        try:
            return super().__call__(engine, prompt, schema, **options)
        finally:
            self.sessions.pop(thread, None)

    def boundary(self):
        reason = super().boundary()
        own = self.sessions.get(threading.get_ident())
        starts = [own] if own is not None else list(self.sessions.values())
        if not reason and any(drift() - start > SLEPT for start in starts):
            reason = "slept"
        return reason


# ----- the plan -----

def prompt_version(text):
    """The version of researcher instructions, as `ask.prompt_version` gives the code's own."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def render(text, question, depth):
    """The researcher's prompt for `question` from instructions `text`, built as `ask.researcher_prompt` builds it from
    `ask.RESEARCHER`."""
    budget = ask.DEPTHS[depth]
    return (text.replace("{searches}", str(budget["searches"])).replace("{sources}", str(budget["sources"])).rstrip()
            + "\n" + question)


def instructions(arm):
    """A researcher arm's own instructions, refused if their text changed since the plan recorded their version."""
    text = Path(arm["prompt"]).read_text()
    if prompt_version(text) != arm["promptVersion"]:
        raise ValueError("The prompt of arm %s changed since the plan was written" % arm["name"])
    return text


def workspace(folder, name, *, releases=None, store=None):
    """An arm's workspace `folder/workspaces/<name>`, made once and never rebuilt: a copy of the knowledge store of the
    workspace root `store` and a link to the graph release that `releases/current.json` names under the root
    `releases`. Arms answer on copies, so no arm changes what it or another arm is measured on."""
    ws = Path(folder).resolve() / "workspaces" / name
    if ws.exists():
        return ws
    part = ws.with_name(name + ".partial")
    shutil.rmtree(part, ignore_errors=True)
    (part / ".oopc/loop").mkdir(parents=True, mode=0o700)
    if releases is not None:
        current = read_json(Path(releases) / "releases/current.json")
        (part / "releases").mkdir()
        (part / "releases" / current["release_id"]).symlink_to(resolve_release(releases).resolve(), True)
        atomic_json(part / "releases/current.json", current)
    if store is not None:
        source = sqlite3.connect(knowledge.database(store).as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(private_sqlite(knowledge.database(part)))
        source.backup(target)
        source.close()
        target.close()
    part.rename(ws)
    return ws


def fingerprint(root):
    """The store's findings and notes, every field, hashed: a store must not change while a study runs on it. Ids and
    statuses alone missed a changed value, condition, excerpt or title (independent review, 2026-10-14)."""
    path, rows = knowledge.database(root), [[], []]
    if path.exists():
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        rows = [db.execute("SELECT * FROM findings ORDER BY id").fetchall(),
                db.execute("SELECT * FROM notes ORDER BY id").fetchall()]
        db.close()
    return {"findings": len(rows[0]), "notes": len(rows[1]),
            "sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]}


def prepare(folder, name, questions, arms, *, engine=engines.CODEX, checker=None):
    """Write the plan (`plan.json`): the questions (each with `id` and `question`), the arms in their base order and
    the checker engine (default: `engine`). Called again with the same plan it returns the stored one; a different
    plan is refused, so a study cannot change under a resumed run. A plain arm without a root gets an empty workspace
    for its ledger. A researcher arm with a `prompt` file keeps its path and version; it is rendered as the code
    renders its own, which is checked here."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    ids = {q.get("id") for q in questions if isinstance(q.get("id"), str) and isinstance(q.get("question"), str)}
    if not NAME.match(name) or not questions or len(ids) != len(questions):
        raise ValueError("A plan needs a plain name and questions with unique ids and text")
    fixed = []
    for arm in arms:
        value = {"name": arm.get("name") or "", "kind": arm.get("kind"), "web": bool(arm.get("web", True)),
                 "depth": arm.get("depth", "standard"), "engine": arm.get("engine", engine)}
        if (not NAME.match(value["name"]) or value["kind"] not in ("researcher", "plain")
                or value["depth"] not in ask.DEPTHS or value["engine"] not in engines.ENGINES
                or value["kind"] == "researcher" and not arm.get("root")
                or arm.get("prompt") and value["kind"] != "researcher"):
            raise ValueError("Not an arm: %r" % (arm,))
        value["root"] = str(Path(arm.get("root") or workspace(folder, value["name"])).resolve())
        if arm.get("prompt"):  # only then, so plans written before 2026-10-18 compare equal
            if two_part():
                raise ValueError(ONE_FILE_ONLY)
            sample = questions[0]["question"]
            if (render(ask.RESEARCHER, sample, value["depth"]) != ask.researcher_prompt(sample, value["depth"])
                    or prompt_version(ask.RESEARCHER) != ask.prompt_version()):
                raise ValueError("This code builds the researcher's prompt differently; an arm's prompt cannot be rendered")
            path = Path(arm["prompt"]).resolve()
            value.update(prompt=str(path), promptVersion=prompt_version(path.read_text()))
        fixed.append(value)
    checker = checker or engine
    if not fixed or len({a["name"] for a in fixed}) != len(fixed) or checker not in engines.ENGINES:
        raise ValueError("A plan needs arms with distinct names and a known checker")
    plan = json.loads(json.dumps({"name": name, "questions": questions, "arms": fixed, "checker": checker}))
    path = folder / "plan.json"
    if path.exists():
        stored = read_json(path)
        if {k: stored.get(k) for k in plan} != plan:
            raise ValueError("A different plan exists in %s; a plan is fixed once written" % folder)
        return stored
    researchers = [a for a in fixed if a["kind"] == "researcher"]
    plan.update(createdAt=now(), promptVersion=ask.prompt_version() if any(not a.get("prompt") for a in researchers)
                else None,
                models={e: engines.ENGINES[e]["model"] for e in sorted({a["engine"] for a in fixed} | {checker})},
                stores={a["name"]: fingerprint(a["root"]) for a in researchers})
    atomic_json(path, plan, private=True)
    return plan


def _unchanged(plan):
    """Refuse to run on another researcher prompt (the code's, or an arm's own), another model or a changed store than
    the plan was written with."""
    if plan.get("promptVersion") and ask.prompt_version() != plan["promptVersion"]:
        raise ValueError("The researcher prompt changed since the plan was written; the arms would not be comparable")
    for engine, model in plan["models"].items():
        if engines.ENGINES[engine]["model"] != model:
            raise ValueError("The %s model changed since the plan was written" % engine)
    for arm in plan["arms"]:
        if arm["name"] in plan["stores"] and fingerprint(arm["root"]) != plan["stores"][arm["name"]]:
            raise ValueError("The store of arm %s changed since the plan was written" % arm["name"])
        if arm.get("prompt"):
            if two_part():
                raise ValueError(ONE_FILE_ONLY)
            instructions(arm)


# ----- one answer, one check -----

def _ledgered(plan, arm, part, question, runner):
    """A runner whose every session is recorded in the arm's token ledger under the study's phase."""
    root, phase = arm["root"], "study:%s:%s:%s" % (plan["name"], arm["name"], part)
    return lambda engine, prompt, schema, **options: calls.invoke(root, phase, question["id"], runner, engine, prompt,
                                                                  schema, **options)


def answer(plan, arm, question, runner):
    """One arm's answer to one question, under the arm's own prompt if it has one. Nothing is saved to the arm's
    store; a researcher's session is traced."""
    root, run = Path(arm["root"]), None
    call = functools.partial(_ledgered(plan, arm, "research", question, runner), arm["engine"], web=arm["web"],
                             timeout=ask.DEPTHS[arm["depth"]]["seconds"])
    title = "Study %s · %s · %s" % (plan["name"], arm["name"], question["question"][:60])
    task = {"study": plan["name"], "arm": arm["name"], "question": question["id"],
            "notice": "Study arm; findings are not saved."}
    if arm["kind"] == "researcher" and two_part():
        # Both turns, as the parity set's researcher arm runs them: the answer under the study's research phase, the
        # findings under its deposit phase.
        if arm.get("prompt"):
            raise ValueError(ONE_FILE_ONLY)
        phase = "study:%s:%s:" % (plan["name"], arm["name"])
        value = parity.answer_ontology(root, question, arm["engine"], runner=runner,
                                       timeout=ask.DEPTHS[arm["depth"]]["seconds"], depth=arm["depth"], web=arm["web"],
                                       phases=(phase + "research", phase + "deposit"), title=title, task=task,
                                       owner=question["id"])
        return {key: value[key] for key in ("answer", "engine", "model", "callId", "metrics", "webActions", "runId",
                                            "depositError") if key in value}
    if arm["kind"] == "plain":
        result = call(parity.DIRECT_PROMPT + question["question"], parity.DIRECT_SCHEMA, tools=None)
    else:
        prompt = (render(instructions(arm), question["question"], arm["depth"]) if arm.get("prompt")
                  else ask.researcher_prompt(question["question"], arm["depth"]))
        release = resolve_release(root)
        run = TraceStore(root).create(release, title, capabilities={"external_source_access": arm["web"]}, task=task)
        try:
            result = call(prompt, ask.ANSWER_SCHEMA,
                          tools=knowledge.research_tools(root, release, run.path.name, "researcher"))
        except engines.EngineError:
            run.finish("failed")
            raise
        run.finish("completed")
    value = {"answer": result["answer"], "engine": result["engine"], "model": result.get("model"),
             "callId": result.get("callId"), "metrics": parity._metrics(result),
             "webActions": parity.web_actions(result)}
    if arm.get("prompt"):
        value["promptVersion"] = arm["promptVersion"]
    return dict(value, runId=run.path.name) if run else value


def check(plan, arm, question, answered, runner):
    """One answer checked by the plan's checker, given its cited sources (with their captured text) and the session's
    record of knowledge searches and web actions."""
    root, text = Path(arm["root"]), answered["answer"].get("answer", "")
    cited = parity.resolve_sources(root, answered["answer"].get("citations"))
    # check_answer(root=...) would capture these itself, but record its call as "answer-check", not the study's phase.
    reviewer.capture_sources(root, cited)
    session = parity.session_record(root, answered.get("runId"), answered.get("webActions"))
    value = reviewer.check_answer(question["question"], text, reviewer.with_captures(root, cited, text),
                                  engine=plan["checker"], runner=_ledgered(plan, arm, "check", question, runner),
                                  session=session)
    return dict(value, citedFraction=parity.cited_fraction(answered["answer"]))


# ----- a run -----

def _path(folder, index, name):
    return Path(folder) / "items" / ("%04d-%s.json" % (index, name))


def _item(folder, index, question, name):
    path = _path(folder, index, name)
    return read_json(path) if path.exists() else {"question": question["id"], "arm": name}


def _ok(value):
    return isinstance(value, dict) and "error" not in value


def _unavailable(guard, needed):
    """Why no question can start now: the stop file, the deadline, or an engine below the floor or signed out."""
    for engine in needed:
        if not guard.eligible(engine):
            return guard.boundary() or ("quota" if guard.signed(engine) else "not-signed-in")
    return None


def _attempts(folder, guard, path, item, part, work):
    """Set `item[part]` from `work()`: tried once more after a timeout or a RETRYABLE failure, and once more after an
    attempt the machine slept through. Every attempt is saved with the item. Quota, not-signed-in, the stop file and
    the deadline raise Stop; any other failure becomes the item's error, with its named reason."""
    retry = engines.RETRYABLE | {"timeout"}
    retried = woke = False
    while True:
        at, hour, before = now(), time.localtime().tm_hour, drift()
        try:
            value, failure = work(), None
        except engines.EngineError as error:
            value, failure = None, error
        slept = drift() - before
        attempt = {"part": part, "at": at, "localHour": hour, "outcome": "failed" if failure else "completed"}
        if failure:
            attempt["reason"] = failure.reason
        if slept > SLEPT:
            attempt["slept"] = round(slept)
        item.setdefault("attempts", []).append(attempt)
        if failure is None:
            item[part] = dict(value, at=at, localHour=hour)
            atomic_json(path, item, private=True)
            return
        atomic_json(path, item, private=True)
        common.emit(folder, "attempt-failed", item=path.stem, part=part, reason=failure.reason,
                    slept=attempt.get("slept"))
        stop = failure.reason if failure.reason in STOPS else guard.boundary()
        if stop:
            raise Stop(stop)
        if slept > SLEPT and not woke:
            woke = True
        elif failure.reason in retry and not retried:
            retried = True
        else:
            item[part] = {"error": failure.summary(), "at": at, "localHour": hour}
            atomic_json(path, item, private=True)
            return


def _items(folder, plan, index, question):
    return {a["name"]: _item(folder, index, question, a["name"]) for a in plan["arms"]}


def _failed(items):
    """How many of a question's items failed: an answer or check that is an error."""
    return sum(any("error" in (item.get(part) or {}) for part in ("answer", "check")) for item in items.values())


def _stale(items):
    """A question stopped part-way (some arm never answered: a stop leaves no answer record, while an answer that
    failed for good keeps its error) whose answers are more than STALE old. An arm that keeps failing does not make
    every resume answer the question again."""
    answered = [datetime.datetime.fromisoformat(i["answer"]["at"]) for i in items.values() if _ok(i.get("answer"))]
    return (bool(answered) and any("answer" not in i for i in items.values())
            and (datetime.datetime.now(datetime.timezone.utc) - min(answered)).total_seconds() > STALE)


def _question(folder, plan, guard, needed, index, question):
    """Question `index`: its arms answered in turn, starting at arm index mod n, then all its answers checked one right
    after the other; what is done stays done."""
    shift = index % len(plan["arms"])
    order = plan["arms"][shift:] + plan["arms"][:shift]
    items = {a["name"]: _item(folder, index, question, a["name"]) for a in order}
    if all(_ok(i.get("answer")) and _ok(i.get("check")) for i in items.values()):
        return
    reason = _unavailable(guard, needed)
    if reason:
        raise Stop(reason)
    common.emit(folder, "question", number=index + 1, id=question["id"])
    if _stale(items):  # every arm answers again, in turn, so none is compared with an answer days older
        for name, item in items.items():
            for part, kept in (("answer", "previousAnswers"), ("check", "previousChecks")):
                if part in item:
                    item.setdefault(kept, []).append(item.pop(part))
            atomic_json(_path(folder, index, name), item, private=True)
        common.emit(folder, "question-answered-again", number=index + 1, id=question["id"])
    for arm in order:
        if not _ok(items[arm["name"]].get("answer")):
            _attempts(folder, guard, _path(folder, index, arm["name"]), items[arm["name"]], "answer",
                      functools.partial(answer, plan, arm, question, guard))
    answered = [a for a in order if _ok(items[a["name"]].get("answer"))]
    if not all(_ok(items[a["name"]].get("check")) for a in answered):
        for arm in answered:  # all of them, one after the other, so no arm meets another day's source access
            item = items[arm["name"]]
            if "check" in item:
                item.setdefault("previousChecks", []).append(item.pop("check"))
            _attempts(folder, guard, _path(folder, index, arm["name"]), item, "check",
                      functools.partial(check, plan, arm, question, item["answer"], guard))


def _pause(guard, seconds):
    """Wait `seconds`, stopping at once for the stop file or the deadline."""
    end = time.time() + seconds
    while True:
        reason = guard.boundary()
        if reason:
            raise Stop(reason)
        if time.time() >= end:
            return
        time.sleep(min(10, max(0, end - time.time())))


def run(folder, *, runner=None, hours=36):
    """Answer and check every question of the plan, resuming where an earlier run stopped, then give the questions
    with a failed item one more pass after PASS_WAIT seconds. Every session goes through `runner`, a Guard (quota floor,
    stop file, deadline, raw streams in `folder`); by default one around `engines.run_session` with a deadline `hours`
    away, and in tests one around a scripted engine. Writes the report and returns the run's state."""
    folder = Path(folder)
    plan = read_json(folder / "plan.json")
    _unchanged(plan)
    guard = runner or Guard(time.time() + hours * 3600, base=folder)
    needed = sorted({a["engine"] for a in plan["arms"]} | {plan["checker"]})
    state = {"status": "running", "startedAt": now()}  # earlier runs' times are on their items' attempts
    atomic_json(folder / "state.json", state, private=True)
    questions = list(enumerate(plan["questions"]))
    try:
        for index, question in questions:
            _question(folder, plan, guard, needed, index, question)
            state.update(reached=index + 1, updatedAt=now())
            atomic_json(folder / "state.json", state, private=True)
        failed = [(i, q) for i, q in questions if _failed(_items(folder, plan, i, q))]
        if failed:  # one more chance for each failed item, then it surfaces as failed
            state.update(phase="one more pass", failedQuestions=len(failed), updatedAt=now())
            atomic_json(folder / "state.json", state, private=True)
            common.emit(folder, "one-more-pass", questions=len(failed), wait=PASS_WAIT)
            _pause(guard, PASS_WAIT)
            for index, question in failed:
                _question(folder, plan, guard, needed, index, question)
        state.update(status="completed", failedItems=sum(_failed(_items(folder, plan, i, q)) for i, q in questions))
    except Stop as stop:
        state.update(status="stopped", stopReason=stop.args[0])
    except BaseException as error:
        state.update(status="interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "crashed",
                     error=str(error)[:400])
        raise
    finally:
        state["finishedAt"] = now()
        atomic_json(folder / "state.json", state, private=True)
        common.emit(folder, "run-" + state["status"], reason=state.get("stopReason") or state.get("error"),
                    failedItems=state.get("failedItems"))
    report(folder)
    return state


# ----- the report -----

def tokens(plan, arm, compared=None):
    """An arm's new tokens from the token ledger in its workspace, never from quota-window percentages: the total over
    every attempt (failures cost tokens too), the median over completed calls for the `compared` question ids. On code
    whose researcher writes its findings in a second turn, that turn is the part `deposit`."""
    prefix = "study:%s:%s:" % (plan["name"], arm["name"])
    rows = [r for r in calls.records(arm["root"]) if r.get("phase", "").startswith(prefix)]
    value = {}
    parts = ("research", "check") + (("deposit",) if any(r["phase"] == prefix + "deposit" for r in rows) else ())
    for part in parts:
        mine = [r for r in rows if r["phase"] == prefix + part]
        done = [r["newTokens"] for r in mine if r["outcome"] == "completed" and r.get("newTokens") is not None
                and (compared is None or r.get("owner") in compared)]
        value[part] = {"calls": len(mine), "total": sum(r.get("newTokens") or 0 for r in mine),
                       "median": statistics.median(done) if done else None,
                       "missingUsage": sum(r.get("newTokens") is None for r in mine)}
    return value


def report(folder):
    """Per arm, over the questions every arm answered and had checked: first the measures that do not depend on
    whether a source opened (contradicted statements, complete answers, sourced results), then passes and
    access-uncertain statements, then new tokens. Writes report.json and report.md and returns the report."""
    folder = Path(folder)
    plan = read_json(folder / "plan.json")
    state = read_json(folder / "state.json") if (folder / "state.json").exists() else {}
    names = [a["name"] for a in plan["arms"]]
    rows = [{n: _item(folder, i, q, n) for n in names} for i, q in enumerate(plan["questions"])]
    compared = [i for i, r in enumerate(rows) if all(_ok(r[n].get("check")) for n in names)]
    ids = {plan["questions"][i]["id"] for i in compared}
    arms = {}
    for arm in plan["arms"]:
        name = arm["name"]
        got = [m for m in (reviewer.measures(rows[i][name]["check"]) for i in compared) if m]
        failed = Counter(part + ":" + r[name][part]["error"]["reason"] for r in rows for part in ("answer", "check")
                         if "error" in (r[name].get(part) or {}))
        arms[name] = {"answered": sum(_ok(r[name].get("answer")) for r in rows),
                      "contradicted": sum(m["contradicted"] for m in got),
                      "complete": sum(m["complete"] is True for m in got),
                      "resultGiven": sum(m["resultGiven"] is True for m in got),
                      "passes": sum(m["pass"] for m in got),
                      "accessUncertain": sum(m["accessUncertain"] for m in got),
                      "tokens": tokens(plan, arm, ids), "failed": dict(failed),
                      "slept": sum(bool(a.get("slept")) for r in rows for a in r[name].get("attempts", []))}
    value = {"name": plan["name"], "checker": plan["checker"], "questions": len(rows), "compared": len(compared),
             "failedItems": sum(_failed(r) for r in rows), "columns": list(COLUMNS), "arms": arms, "state": state,
             "at": now()}
    atomic_json(folder / "report.json", value, private=True)
    atomic_bytes(folder / "report.md", _markdown(value).encode("utf-8"), private=True)
    return value


def _markdown(value):
    state = value["state"]
    lines = ["# " + value["name"], "",
             "%d of %d questions answered and checked by every arm; checker %s; run %s%s." % (
                 value["compared"], value["questions"], value["checker"], state.get("status", "not started"),
                 ", stopped: " + state["stopReason"] if state.get("stopReason") else ""),
             "Contradicted statements, complete answers and sourced results do not depend on whether a source opened "
             "during the check; passes and access-uncertain statements do. New tokens are from the token ledger: the "
             "total over every attempt, the median over the compared questions' answers.", "",
             "| Arm | Answered | Contradicted | Complete | Sourced result | Passes | Access-uncertain "
             "| Research tokens (total) | (median) | Check tokens (total) |", "| --- |" + " ---: |" * 9]
    for name, arm in value["arms"].items():
        cells = [arm[c] for c in COLUMNS[:-1]] + [arm["tokens"]["research"]["total"],
                                                   arm["tokens"]["research"]["median"], arm["tokens"]["check"]["total"]]
        lines.append("| %s | %s |" % (name, " | ".join("–" if x is None else str(x) for x in cells)))
    failed = ["%s %s" % (name, ", ".join("%s %d" % kv for kv in sorted(arm["failed"].items())))
              for name, arm in value["arms"].items() if arm["failed"]]
    return "\n".join(lines + (["", "Failed items (%d, each tried once more): %s." % (value["failedItems"],
                                                                                    "; ".join(failed))]
                              if failed else [])) + "\n"
