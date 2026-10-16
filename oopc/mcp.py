"""Dependency-free MCP stdio transport with a narrow evidence-access tool surface.

Protocol: 2025-06-18, line-delimited JSON-RPC. Logs never go to stdout.
"""
import io
import json
import sys

from .graph import Graph
from .trace import TraceStore
from . import __version__

STR = {"type":"string"}
INT = {"type":"integer","minimum":1,"maximum":500}
OFFSET = {"type":"integer","minimum":0}
FILTERS = {key:STR for key in ("type","status","layer","predicate","property","process","application","environment","source","facet")}
SPECS = {
    "describe_vocabulary": ("Read ontology definitions, meanings, and required qualifiers.", {"term":STR}, []),
    "search": ("Search evidence records. Returned results are not traversals. Seed records are unverified.", {"q":STR,"limit":INT,"offset":OFFSET,**FILTERS}, []),
    "get_record": ("Retrieve one identified record with its exact qualifiers and validation status.", {"id":STR}, ["id"]),
    "get_claims": ("Retrieve source-qualified assertions, preserving their context.", {"subject":STR,"object":STR,"limit":INT,"offset":OFFSET,**FILTERS}, []),
    "get_evidence": ("Retrieve exact evidence metadata and source locators for a record.", {"id":STR}, ["id"]),
    "traverse": ("Explicitly follow directed edges. Paths in the result are the actual recorded traversals.", {"start":STR,"depth":{"type":"integer","minimum":1,"maximum":4},"direction":{"type":"string","enum":["in","out","both"]},"limit":INT,**FILTERS}, ["start"]),
    "attach_artifact": ("Record a final answer and its citations in this private task. Does not publish or validate claims.", {"artifact":{"type":"object"}}, ["artifact"]),
}


def _utf8_text_stream(stream):
    # MCP pipes carry UTF-8 regardless of the host's redirected-console locale.
    # Preserve supplied text-only streams and already configured socket wrappers.
    if (isinstance(stream, io.TextIOWrapper)
            and stream.encoding.lower().replace("_", "-") not in {"utf-8", "utf8"}):
        stream.reconfigure(encoding="utf-8", errors="strict")
    return stream


class MCP:
    def __init__(self, root, release, run_id=None, agent_id="agent"):
        self.root = root
        self.store = TraceStore(root)
        self.run = self.store.run(run_id) if run_id else self.store.create(release,"MCP research session")
        self.graph = Graph(release,self.run,agent_id)
        self.agent_id = agent_id

    def tools(self):
        return {"tools":[{"name":name,"description":description + (
                              " Predicate filters require exact relation IDs from describe_vocabulary; unknown names are errors."
                              if "predicate" in props else ""),
                          "inputSchema":{"type":"object","properties":props,"required":required,"additionalProperties":False},
                          "annotations":{"readOnlyHint":name != "attach_artifact","destructiveHint":False,"openWorldHint":False}}
                         for name,(description,props,required) in SPECS.items()]}

    def _validate(self, name, args):
        if name not in SPECS or not isinstance(args,dict):
            raise ValueError("Unknown tool or invalid arguments")
        _,props,required = SPECS[name]
        if set(args)-set(props) or any(key not in args for key in required):
            raise ValueError("Unexpected or missing tool arguments")
        for key,value in args.items():
            spec = props[key]
            valid = {"string":isinstance(value,str),"integer":type(value) is int,
                     "object":isinstance(value,dict),"boolean":type(value) is bool}[spec["type"]]
            if not valid or (isinstance(value,str) and len(value)>10000):
                raise ValueError("Invalid argument: "+key)
            if ("minimum" in spec and value < spec["minimum"]) or ("maximum" in spec and value > spec["maximum"]):
                raise ValueError("Argument out of range: "+key)
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError("Invalid argument choice: "+key)

    def call(self, name, args):
        try:
            self._validate(name, args)
        except (ValueError, KeyError, TypeError) as error:
            # Graph records failures after dispatch; validation failures happen
            # before Graph sees the call and require their own empty event.
            self.run.record("mcp."+str(name), {"tool":name, "arguments":args},
                            {"error":str(error)}, agent_id=self.agent_id, status="error")
            raise
        if name == "describe_vocabulary": return self.graph.describe(**args)
        if name == "search": return self.graph.search(**args)
        if name == "get_record": return self.graph.get(args["id"])
        if name == "get_claims": return self.graph.claims(**args)
        if name == "get_evidence": return self.graph.evidence(args["id"])
        if name == "traverse": return self.graph.traverse(**args)
        if name == "attach_artifact": return self.run.artifact(args["artifact"],self.agent_id)
        raise ValueError(name)

    def handle(self, message):
        if (not isinstance(message,dict) or message.get("jsonrpc")!="2.0" or
                not isinstance(message.get("method"), str) or
                ("id" in message and (type(message["id"]) not in (str, int)))):
            return {"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"Invalid JSON-RPC request"}}
        if "id" not in message:
            return None
        response = {"jsonrpc":"2.0","id":message["id"]}
        try:
            method,params = message.get("method"),message.get("params",{})
            if method == "initialize":
                result = {"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":False}},
                          "serverInfo":{"name":"oopc","version":__version__},
                          "instructions":"Evidence access is recorded locally. Seed claims remain unverified. Preserve source scope. Task co-use never establishes chemistry facts."}
            elif method == "ping": result = {}
            elif method == "tools/list":
                if not isinstance(params, dict) or params.get("cursor") is not None:
                    response["error"] = {"code":-32602,"message":"Tool listing is a single page; cursor is unsupported"}
                    return response
                result = self.tools()
            elif method == "tools/call":
                try:
                    if not isinstance(params, dict) or "name" not in params:
                        error = "Tool call requires a name and an arguments object"
                        self.run.record("mcp.invalid_call", {"params":params}, {"error":error},
                                        agent_id=self.agent_id, status="error")
                        raise ValueError(error)
                    value = self.call(params["name"],params.get("arguments",{}))
                    result = {"content":[{"type":"text","text":json.dumps(value,ensure_ascii=False)}],"structuredContent":value,"isError":False}
                except (ValueError,KeyError,TypeError,FileNotFoundError) as error:
                    result = {"content":[{"type":"text","text":str(error)}],"isError":True}
            else:
                response["error"] = {"code":-32601,"message":"Method not found"}
                return response
            response["result"] = result
        except Exception as error:
            response["error"] = {"code":-32603,"message":str(error)}
        return response

    def serve(self, input_stream=None, output_stream=None):
        source = _utf8_text_stream(input_stream or sys.stdin)
        target = _utf8_text_stream(output_stream or sys.stdout)
        while True:
            line = source.readline(2_000_001)
            if not line:
                break
            if len(line)>2_000_000:
                break
            try:
                response = self.handle(json.loads(line))
            except json.JSONDecodeError:
                response = {"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Invalid JSON"}}
            if response is not None:
                target.write(json.dumps(response,ensure_ascii=False)+"\n")
                target.flush()
