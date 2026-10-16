"""Explicit synthetic zero-use reviewer receipts; never live scientific evidence."""
import copy
from oopc.admission import canonical_hash
from oopc.reviewer_format import PROTOCOL, ROLE, preflight_condition


def bind_preflight(row, configuration=None):
    if row.get("adapterVersion") not in {"0.6.1", "0.6.4", "0.6.5"}:
        return row
    if row.get("adapterVersion") in {"0.6.4", "0.6.5"}:
        from oopc.benchmark_adapter import SOLVER_EXECUTION_CONDITION
        row["solverExecutionCondition"] = copy.deepcopy(SOLVER_EXECUTION_CONDITION)
        if configuration is not None:
            configuration["solverExecutionCondition"] = copy.deepcopy(SOLVER_EXECUTION_CONDITION)
    evaluation = row["evaluation"]
    condition = preflight_condition(captured_sources=bool(row.get("reviewerSourceCondition")))
    row["reviewerPreflight"] = copy.deepcopy(condition)
    evaluation["reviewerPreflight"] = copy.deepcopy(condition)
    if configuration is not None:
        configuration["reviewerPreflight"] = copy.deepcopy(condition)
        if row.get("reviewerSourceCondition"):
            configuration["reviewerSourceCondition"] = copy.deepcopy(row["reviewerSourceCondition"])
    if row.get("reviewerSourceCondition"):
        captured = row["reviewerSourceCondition"]
        evaluation["reviewerSourceCondition"] = copy.deepcopy(captured)
        evaluation["capturedSourceAccess"] = {"role":ROLE, "sessionId":evaluation["reviewerSessionId"],
            "protocol":captured["protocol"], "bundleHash":captured["bundleHash"]}
        evaluation.pop("reviewerPreflightAccess", None)
        return row
    final_hash = canonical_hash({"syntheticFinalResponse":evaluation["reviewerSessionId"]})
    receipt = {"protocol":PROTOCOL, "conditionHash":canonical_hash(condition), "role":ROLE,
        "sessionId":evaluation["reviewerSessionId"], "allowedCorpusHash":row["allowedCorpusHash"],
        "solverEvidenceCapabilitiesHash":row["solverEvidenceCapabilitiesHash"],
        "frozenAvailabilityHash":evaluation["frozenAvailabilityHash"],
        "sourceOptions":{"disable_shell":True,"web_search":"live"}, "events":[],
        "eventsHash":canonical_hash([]), "callCount":0, "draftCallCount":0, "budgetExhausted":False,
        "finalAssessmentDraftHash":None, "matchingDraftEventIds":[], "finalDraftRepresentationChecked":False,
        "finalResponseHash":final_hash, "deliveryConfirmed":False, "scientificJudgment":False}
    receipt["receiptHash"] = canonical_hash(receipt)
    evaluation["reviewerPreflightAccess"] = receipt
    evaluation["reviewerPreflightResponseHash"] = final_hash
    return row
