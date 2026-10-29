"""Publish a version of this repository to the public one, without the development history.

    python tools/publish_public.py                      # what main would add (nothing is pushed)
    python tools/publish_public.py --push               # add main as one commit on the public main
    python tools/publish_public.py v0.14.0 --push --tag v0.14.0 -m "oopc 0.14.0"

The public repository holds one commit per published version. Each is the tree of a development
revision without the development records listed under `internal` in config/public-files.json and
local editor settings (.claude/); its parent is the public main, so no development commit and no
excluded file ever reaches it. The commit names its development revision in a trailer. A revision
that adds nothing, or whose files name this machine's home directory, is refused. Run the suite from
a fresh clone first (AGENTS.md). Visibility is set on GitHub, for example
    gh repo edit bsavoie/open-ontology-of-polymer-chemistry --visibility public --accept-visibility-change-consequences
Standard library and git only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = "https://github.com/bsavoie/open-ontology-of-polymer-chemistry.git"
LOCAL = [".claude/"]
FETCHED = "refs/public/main"  # The public main as last fetched; never pushed anywhere.


def git(root, *args, env=None, data=None):
    result = subprocess.run(["git", *args], cwd=root, input=data, capture_output=True, text=True,
                            env={**os.environ, **(env or {})})
    if result.returncode:
        raise RuntimeError("git " + " ".join(args[:2]) + " failed: " + result.stderr.strip())
    return result.stdout.strip()


def excluded(root, rev):
    selection = json.loads(git(root, "show", rev + ":config/public-files.json"))
    return selection.get("internal", []) + LOCAL


def snapshot_tree(root, rev, paths):
    """The tree of `rev` without `paths`, built in a scratch index so the checkout is untouched."""
    with tempfile.TemporaryDirectory() as scratch:
        env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(root, "read-tree", rev, env=env)
        git(root, "rm", "-r", "--cached", "--quiet", "--ignore-unmatch", "--", *[p.rstrip("/") for p in paths], env=env)
        return git(root, "write-tree", env=env)


def message_with(message, trailer):
    """Append a trailer to the message's trailer block, or start one."""
    last = message.rstrip().split("\n\n")[-1]
    joiner = "\n" if all(re.match(r"^[\w-]+: ", line) for line in last.splitlines()) and "\n\n" in message.strip() else "\n\n"
    return message.rstrip() + joiner + trailer + "\n"


def publish(root=ROOT, rev="main", to=PUBLIC, push=False, tag=None, message=None, tag_message=None):
    commit = git(root, "rev-parse", "--verify", rev + "^{commit}")
    paths = excluded(root, commit)
    tree = snapshot_tree(root, commit, paths)
    found = subprocess.run(["git", "grep", "-I", "-l", "-F", str(Path.home()), tree], cwd=root, capture_output=True, text=True)
    if found.returncode not in (0, 1):
        raise RuntimeError("git grep failed: " + found.stderr.strip())
    if found.stdout.split():
        raise ValueError("Files name this machine's home directory: " + ", ".join(found.stdout.split()))
    parent = None
    if git(root, "ls-remote", to, "refs/heads/main"):
        git(root, "fetch", "--quiet", "--no-tags", to, "+refs/heads/main:" + FETCHED)
        parent = git(root, "rev-parse", FETCHED)
        if git(root, "rev-parse", parent + "^{tree}") == tree:
            return {"published": False, "reason": "The public main already has these files", "parent": parent}
    if tag and git(root, "ls-remote", "--tags", to, "refs/tags/" + tag):
        raise ValueError("The public repository already has tag " + tag)
    version = re.search(r'__version__ = "([^"]+)"', git(root, "show", commit + ":oopc/__init__.py")).group(1)
    message = message_with(message or "oopc %s" % version, "Development-revision: " + commit)
    date = git(root, "log", "-1", "--format=%cI", commit)
    changes = git(root, "diff", "--stat", parent + "^{tree}", tree) if parent else git(root, "ls-tree", "-r", "--name-only", tree)
    plan = {"published": False, "revision": commit, "version": version, "parent": parent, "excluded": paths,
            "files": len(git(root, "ls-tree", "-r", "--name-only", tree).splitlines()), "changes": changes, "message": message}
    if not push:
        return plan
    created = git(root, "commit-tree", tree, *(["-p", parent] if parent else []),
                  env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}, data=message)
    refs = [created + ":refs/heads/main"]
    if tag:
        if tag_message is None and git(root, "tag", "-l", tag):
            tag_message = git(root, "tag", "-l", "--format=%(contents)", tag)
        ident = git(root, "var", "GIT_COMMITTER_IDENT")
        body = "object %s\ntype commit\ntag %s\ntagger %s\n\n%s\n" % (created, tag, ident, (tag_message or message).strip())
        refs.append(git(root, "mktag", data=body) + ":refs/tags/" + tag)
    # Atomic: the public main moves only by fast-forward from the fetched parent, and only with its tag.
    git(root, "push", "--quiet", "--atomic", to, *refs)
    git(root, "update-ref", FETCHED, created)
    return {**plan, "published": True, "commit": created}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("rev", nargs="?", default="main", help="the development revision to publish (default main)")
    parser.add_argument("--push", action="store_true", help="create the commit and push it; without it nothing is pushed")
    parser.add_argument("--tag", help="also tag the public commit; a local tag of that name lends its message")
    parser.add_argument("-m", "--message", help='commit message (default "oopc VERSION")')
    parser.add_argument("--tag-message", help="tag message (default: the local tag's, else the commit message)")
    parser.add_argument("--to", default=PUBLIC, help="the public repository (default %(default)s)")
    args = parser.parse_args(argv)
    result = publish(ROOT, args.rev, args.to, args.push, args.tag, args.message, args.tag_message)
    if "revision" not in result:
        print(result["reason"] + " (" + result["parent"][:7] + "); nothing to publish.")
        return 0
    print("Revision %s (oopc %s) -> %s, %d files, without %s"
          % (result["revision"][:7], result["version"], args.to, result["files"], ", ".join(result["excluded"])))
    print("Parent: " + (result["parent"][:7] if result["parent"] else "none (first commit)"))
    print(result["changes"].splitlines()[-1] if result["parent"] else "")
    print("\n" + result["message"])
    print("Published %s." % result["commit"][:7] if result["published"] else "Nothing pushed; add --push to publish.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
