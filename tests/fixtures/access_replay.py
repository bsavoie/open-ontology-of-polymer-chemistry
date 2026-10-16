"""Shared fixtures moved from tests/test_access_replay.py (TD-17)."""
import copy
import io
import json
import shutil
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from oopc.graph import Graph
from oopc.mcp import MCP
from oopc.release import build_release, verify_release
from oopc.server import make_server
from oopc.trace import TraceStore, import_replay
from oopc.util import canonical, digest
from oopc.vocabulary import get_ontology


def fixture_records():
    nodes = [{"@id": rid, "@type": "PolymerConcept", "label": label, "status": "seed", "layer": "science"}
             for rid, label in (("wop-000001", "Material Alpha"), ("wop-000002", "Material Beta"), ("wop-000003", "Disconnected Gamma"))]
    nodes += [{"@id": "document:open", "@type": "Document", "label": "Open paper", "status": "seed", "layer": "provenance"},
              {"@id": "evidence:one", "@type": "Evidence", "label": "Source locator", "status": "seed", "layer": "provenance",
               "document": "document:open", "locator": "Section 3", "lineageId": "lab", "accessedDate": "2026-09-10",
               "accessStatus": "anonymous_full_content", "reuseStatus": "publicly_accessible_citation_only", "permissionBasis": "Cite and paraphrase",
               "url": "https://example.org/open"},
              {"@id": "claim:ab", "@type": "Claim", "label": "Alpha related to Beta", "status": "seed", "layer": "science",
               "subject": "wop-000001", "predicate": "related", "object": "wop-000002", "context": {"scopeNote": "Fixture relation only"}, "evidence": ["evidence:one"]}]
    return nodes
