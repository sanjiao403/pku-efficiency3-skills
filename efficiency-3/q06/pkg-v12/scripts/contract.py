"""contract.py - read the case's output contract and keep result.json compliant.

Case contracts arrive in four shapes, all of which have been seen in the wild:

    {"deliverable": "中文描述", ...}            -> field: description
    {"type":"object","properties":{...},"required":[...]}  -> JSON Schema
    ["deliverable","slides",...]                -> bare list of field names
    (absent)                                    -> a documented default set

The rule is: **every contract field appears at top level of result.json**, as
``str`` (empty string) when there is nothing honest to put there, ``list`` /
``dict`` when the field is a collection.  Never ``null``.  Fields we could not
understand are listed in ``contract_unresolved`` instead of being guessed.
"""
from __future__ import annotations

import json
import re

DEFAULT_FIELDS = [
    "deliverable", "deck", "slides", "evidence_map", "render", "notes",
    "case_id", "status", "sources", "uncertainty", "changes",
]

# which of our produced values should fill a given contract field name
_FIELD_ALIASES = {
    "deck": ["deck", "presentation", "pptx", "slides_file", "file"],
    "slides": ["slides", "slide_plan", "pages", "outline", "structure"],
    "evidence_map": ["evidence_map", "evidence", "citations", "sources_map",
                     "slide_evidence", "traceability", "locators"],
    "render": ["render", "preview", "pdf", "rendered", "artifacts", "outputs"],
    "notes": ["notes", "speaker_notes", "script", "narration"],
    "deliverable": ["deliverable", "result", "output", "main"],
    "template": ["template", "master", "layout", "theme"],
    "uncertainty": ["uncertainty", "risks", "open_questions", "limitations"],
    "sources": ["sources", "inputs", "materials"],
    "changes": ["changes", "change_log", "changelog", "revision_history"],
    "status": ["status", "state"],
    "case_id": ["case_id", "id", "case"],
}

_LIST_HINTS = re.compile(r"(slides|notes|evidence|sources|uncertainty|changes|"
                         r"artifacts|files|outputs|locators|risks|questions)", re.I)


def detect(case: dict) -> dict:
    """Resolve the contract into {fields:[{name, kind, description}], source}."""
    raw = None
    source = "absent"
    for key in ("output_contract", "outputContract", "contract", "outputs"):
        if isinstance(case.get(key), (dict, list)):
            raw = case[key]
            source = key
            break
    if raw is None and isinstance(case.get("task"), dict):
        for key in ("output_contract", "outputContract", "contract"):
            if isinstance(case["task"].get(key), (dict, list)):
                raw = case["task"][key]
                source = f"task.{key}"
                break
    if raw is None:
        return {"source": "default", "fields": [{"name": f, "kind": _kind_of(f),
                                                 "description": ""} for f in DEFAULT_FIELDS],
                "unresolved": []}

    fields, unresolved = [], []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                fields.append({"name": item, "kind": _kind_of(item), "description": ""})
            elif isinstance(item, dict) and item.get("name"):
                fields.append({"name": item["name"],
                               "kind": item.get("type") or _kind_of(item["name"]),
                               "description": item.get("description", "")})
            else:
                unresolved.append(str(item)[:80])
    elif isinstance(raw, dict):
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else None
        if props:
            for name, spec in props.items():
                spec = spec if isinstance(spec, dict) else {}
                fields.append({"name": name,
                               "kind": spec.get("type") or _kind_of(name),
                               "description": spec.get("description", ""),
                               "required": name in (raw.get("required") or [])})
            for req in raw.get("required") or []:
                if req not in props:
                    fields.append({"name": req, "kind": _kind_of(req), "description": "",
                                   "required": True})
        else:
            for name, desc in raw.items():
                if isinstance(desc, dict):
                    fields.append({"name": name, "kind": desc.get("type") or _kind_of(name),
                                   "description": str(desc.get("description", ""))})
                else:
                    fields.append({"name": name, "kind": _kind_of(name),
                                   "description": str(desc)[:200]})
    if not fields:
        unresolved.append("contract present but no field names could be read")
    return {"source": source, "fields": fields, "unresolved": unresolved}


def _kind_of(name: str) -> str:
    return "array" if _LIST_HINTS.search(name) else "string"


def default_value(field: dict, produced: dict):
    kind = (field.get("type") or field.get("kind") or "string")
    name = field.get("name", "")
    target = _match_name(name, produced)
    if target is not None:
        return produced[target]
    if kind in ("array", "list") or _LIST_HINTS.search(name):
        return []
    if kind in ("object", "dict") or kind == "object":
        return {}
    return ""


def _match_name(name: str, produced: dict):
    low = name.lower()
    if low in produced:
        return low
    for key, aliases in _FIELD_ALIASES.items():
        if low == key or any(a in low for a in aliases):
            if key in produced:
                return key
    # last resort: substring match against produced keys
    for key in produced:
        if key in low:
            return key
    return None


def fill(case: dict, produced: dict, *, contract: dict | None = None) -> dict:
    """Build a contract-complete result dict from what we actually produced."""
    contract = contract or detect(case)
    result = {}
    case_id = case.get("case_id") or case.get("id") or (case.get("case") or {}).get("case_id")
    for field in contract["fields"]:
        name = field["name"]
        result[name] = default_value(field, produced)
    # always keep the platform's own identifiers and honest status
    if case_id is not None:
        result.setdefault("case_id", case_id)
        result["case_id"] = case_id
    result.setdefault("status", produced.get("status", "partial"))
    result["contract"] = {
        "source": contract["source"],
        "fields": [f["name"] for f in contract["fields"]],
        "unresolved": contract.get("unresolved") or [],
    }
    for key in ("sources", "uncertainty", "changes", "render", "evidence_map",
                "deck", "slides", "notes", "deliverable", "template"):
        if key in produced and key not in result:
            result[key] = produced[key]
    # every other artefact field the run really produced is kept too: the
    # contract is a floor, not a ceiling (audit/validation/inventory/performance)
    for key, val in produced.items():
        if key in result or val is None:
            continue
        result[key] = val
    return result


def missing_for_contract(result: dict, contract: dict) -> list[str]:
    bad = []
    for f in contract["fields"]:
        name = f["name"]
        if name not in result:
            bad.append(f"missing field: {name}")
            continue
        val = result[name]
        if val is None:
            bad.append(f"null value: {name}")
        elif isinstance(val, str) and not val.strip() and (f.get("required") or
                                                           name in ("deliverable", "slides")):
            bad.append(f"empty required field: {name}")
    return bad


def load_case(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        data = {"task": str(data)}
    return data
