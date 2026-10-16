"""Optional local OTLP JSON projection; no telemetry client or network export."""
from datetime import datetime
from .util import digest


def export_spans(run):
    events=run.events()["events"]
    parents={event["event_id"]:event["span_id"] for event in events}
    spans=[]
    for event in events:
        end=int(datetime.fromisoformat(event["timestamp"]).timestamp()*1_000_000_000)
        attributes={"oopc.run_id":event["run_id"],"oopc.event_id":event["event_id"],
                    "oopc.agent_id":event["agent_id"],"oopc.kind":event["kind"],
                    "oopc.release_id":event["release_id"],"oopc.payload_sha256":event["payload_hash"]}
        span={"traceId":event.get("trace_id",digest(event["run_id"])[:32]),"spanId":event["span_id"],
              "name":event["operation"],"kind":1,
              "startTimeUnixNano":str(end-int(event["duration_ms"]*1_000_000)),"endTimeUnixNano":str(end),
              "attributes":[{"key":key,"value":{"stringValue":value}} for key,value in attributes.items()],
              "status":{"code":2 if event["status"]=="error" else 1}}
        if event.get("parent_event_id"):span["parentSpanId"]=parents[event["parent_event_id"]]
        spans.append(span)
    return {"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"oopc"}}]},
                              "scopeSpans":[{"scope":{"name":"oopc.access","version":"0.1.0"},"spans":spans}]}]}
