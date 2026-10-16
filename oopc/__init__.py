"""Open Ontology of Polymer Chemistry.

The core reader and inspector have no third-party runtime dependencies.
"""
__version__ = "0.12.0"


def __getattr__(name):
    if name == "Graph":
        from .graph import Graph
        return Graph
    if name == "TraceStore":
        from .trace import TraceStore
        return TraceStore
    raise AttributeError(name)
