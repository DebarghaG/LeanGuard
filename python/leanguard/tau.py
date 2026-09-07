"""Adapters for a pinned, instrumented text-domain τ-bench baseline.

This module reads authoritative domain state, never task solutions or evaluation
criteria. Decisions about that state are made by the compiled Lean policy pack.
"""

from __future__ import annotations

import importlib
import json
import threading
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from .engine import digest
from .host import ReadOnlyToolError, Snapshot

REVISION = "672227c6b6676edc20d57ea53b7000262aae77b9"
EST = timezone(timedelta(hours=-5))
MONEY_KEYS = {
    "price",
    "amount",
    "balance",
    "total_due",
    "monthly_price",
    "data_refueling_price_per_gb",
    "total_amount_due",
    "payment_amount",
}


def jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def wire_value(environment, value):
    """Use τ-bench's wire representation once, including date and model handling."""
    if isinstance(value, str):
        return value
    return json.loads(environment.to_json_str(value))


def wire_text(value):
    return value if isinstance(value, str) else json.dumps(value, allow_nan=False)


def scaled(value, factor: int) -> int:
    result = Decimal(str(value)) * factor
    if not result.is_finite() or result != result.to_integral_value():
        raise ValueError("quantity is not exactly representable at the declared precision")
    return int(result)


def epoch(value: str) -> int:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EST)
    return int(parsed.timestamp())


def normalize(value, key=""):
    """Exact unit conversion: money to cents and GB to integer thousandths."""
    if isinstance(value, dict):
        result = {k: normalize(v, k) for k, v in value.items()}
        for k, v in value.items():
            if k.endswith("_gb") or k == "gb_amount":
                result[k + "_milli"] = scaled(v, 1000)
            if k == "created_at":
                result["created_epoch"] = epoch(v)
            if k == "contract_end_date":
                # A date stays valid throughout that EST calendar day.
                result["contract_end_epoch"] = None if v is None else epoch(v) + 86399
        if key == "prices":
            result = {k: scaled(v, 100) for k, v in value.items()}
        return result
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if key in MONEY_KEYS and type(value) in (int, float):
        return scaled(value, 100)
    return value


class TauAdapter:
    def __init__(self, domain: str, environment=None):
        if domain not in {"retail", "airline", "telecom"}:
            raise ValueError("unsupported text domain")
        self.domain = domain
        if environment is None:
            factory = importlib.import_module(f"tau2.domains.{domain}.environment")
            environment = factory.get_environment()
        self.environment = environment
        self.lock = threading.RLock()
        self.user_evidence: dict = {}

    @property
    def clock(self):
        if self.domain == "airline":
            return epoch("2024-05-15T15:00:00")
        if self.domain == "telecom":
            return epoch("2025-02-25T12:08:00")
        return epoch("2024-05-15T15:00:00")

    def tool_schemas(self):
        return {tool.name: tool.openai_schema["function"] for tool in self.environment.get_tools()}

    def mutating(self, action):
        return self.environment._is_mutating_tool(action)

    def snapshot(self, action: str, arguments: dict, customer: str) -> Snapshot:
        if set(self.user_evidence) - {"cancellation_reason", "compensation_reservation"}:
            raise ValueError("intent evidence cannot replace authoritative domain facts")
        if any(not isinstance(value, str) for value in self.user_evidence.values()):
            raise TypeError("intent evidence must contain strings")
        schemas = self.tool_schemas()
        if action not in schemas:
            return Snapshot("unknown", "unknown", {}, deepcopy(arguments))
        from jsonschema import validate

        validate(arguments, schemas[action]["parameters"])
        db = jsonable(self.environment.tools.db)
        user_db = jsonable(self.environment.user_tools.db) if self.environment.user_tools else None
        revision = digest({"db": db, "user": user_db, "evidence": self.user_evidence})
        if self.domain in {"retail", "airline"}:
            raw, resource = self._commerce(db, action, arguments, customer)
        else:
            raw, resource = self._telecom(db, action, arguments, customer)
        raw.update(deepcopy(self.user_evidence))
        normalized = normalize(arguments)
        return Snapshot(
            resource,
            revision,
            normalize(raw),
            normalized,
            max(0, normalized.get("amount", 0)),
            {"money": "USD cents", "time": "Unix seconds", "*_gb_milli": "thousandths of GB"},
        )

    def _commerce(self, db, action, arguments, customer):
        resolved = ""
        if action == "find_user_id_by_email":
            resolved = next(
                (
                    id
                    for id, u in db["users"].items()
                    if u["email"].lower() == arguments["email"].lower()
                ),
                "",
            )
        elif action == "find_user_id_by_name_zip":
            resolved = next(
                (
                    id
                    for id, u in db["users"].items()
                    if u["name"]["first_name"].lower() == arguments["first_name"].lower()
                    and u["name"]["last_name"].lower() == arguments["last_name"].lower()
                    and u["address"]["zip"] == arguments["zip"]
                ),
                "",
            )
        facts = {
            "customer_id": customer,
            "lookup_customer_id": resolved,
            "user": db["users"].get(customer, {}),
        }
        resource = resolved or arguments.get("user_id", customer)
        if "order_id" in arguments:
            resource = arguments["order_id"]
            order = db["orders"].get(resource, {})
            facts["order"] = order
            ids = {item["product_id"] for item in order.get("items", [])}
            facts["products"] = {id: db["products"][id] for id in ids}
        if self.domain == "airline":
            reservation_id = arguments.get("reservation_id")
            if action == "send_certificate":
                reservation_id = self.user_evidence.get("compensation_reservation")
            if reservation_id:
                resource = reservation_id
                facts["reservation"] = db["reservations"].get(reservation_id, {})
            flights = list(arguments.get("flights", []))
            flights += facts.get("reservation", {}).get("flights", [])
            ids = {f["flight_number"] for f in flights}
            facts["flights"] = {id: db["flights"][id] for id in ids if id in db["flights"]}
            if arguments.get("user_id") and not customer:
                facts["user"] = db["users"].get(arguments["user_id"], {})
        return facts, resource or "public"

    def _telecom(self, db, action, arguments, customer):
        customers = {u["customer_id"]: u for u in db["customers"]}
        candidates = []
        if action == "get_customer_by_id":
            candidates = [
                u for u in db["customers"] if u["customer_id"] == arguments["customer_id"]
            ]
        elif action == "get_customer_by_phone":
            candidates = [
                u for u in db["customers"] if u["phone_number"] == arguments["phone_number"]
            ]
        elif action == "get_customer_by_name":
            candidates = [
                u
                for u in db["customers"]
                if u["full_name"] == arguments["full_name"]
                and u["date_of_birth"] == arguments["dob"]
            ]
        resolved = candidates[0]["customer_id"] if len(candidates) == 1 else ""
        user = customers.get(customer, {})
        facts = {
            "customer_id": customer,
            "lookup_customer_id": resolved,
            "user": user,
            "bills": [b for b in db["bills"] if b["bill_id"] in user.get("bill_ids", [])],
            "customer_lines": [l for l in db["lines"] if l["line_id"] in user.get("line_ids", [])],
        }
        resource = resolved or arguments.get("line_id") or arguments.get("bill_id")
        resource = resource or arguments.get("id") or customer or "public"
        facts["detail_type"] = "unknown"
        for kind, collection, id_key in (
            ("customer", "customers", "customer_id"),
            ("line", "lines", "line_id"),
            ("bill", "bills", "bill_id"),
            ("plan", "plans", "plan_id"),
            ("device", "devices", "device_id"),
        ):
            if any(o[id_key] == resource for o in db[collection]):
                facts["detail_type"] = kind
        for obj, collection, id_key in (("line", "lines", "line_id"), ("bill", "bills", "bill_id")):
            found = next((o for o in db[collection] if o[id_key] == resource), None)
            if found:
                facts[obj] = found
        if "line" in facts:
            facts["plan"] = next(p for p in db["plans"] if p["plan_id"] == facts["line"]["plan_id"])
        return facts, resource

    def execute(self, action: str, arguments: dict):
        read_only = not self.mutating(action)
        before = (self.environment.get_db_hash(), self.environment.get_user_db_hash())
        try:
            result = self.environment.make_tool_call(action, requestor="assistant", **arguments)
        except Exception as exc:
            after = (self.environment.get_db_hash(), self.environment.get_user_db_hash())
            if read_only and before == after:
                raise ReadOnlyToolError(str(exc)) from exc
            raise
        self.environment.sync_tools()
        return wire_value(self.environment, result)

    def user_action(self, host, action: str, arguments: dict):
        """User simulator actions have an independent role and are observed after synchronization."""
        with host._lock, self.lock:
            result = self.environment.make_tool_call(action, requestor="user", **arguments)
            self.environment.sync_tools()
            host.observe_trusted("user_action", host.customer(), action=action)
            return wire_value(self.environment, result)


class GuardedEnvironment:
    """Proxy for τ-bench orchestration; preserve agent/user tool separation.

    `confirmation` must be a trusted UI callback returning a Boolean after displaying
    the proposal, not an agent inference. All runs through this wrapper are instrumented.
    """

    def __init__(self, host, confirmation=None):
        self.host = host
        self.confirmation = confirmation
        self.environment = host.adapter.environment

    def __getattr__(self, name):
        return getattr(self.environment, name)

    def _assistant_call(self, action, arguments, request_id=None):
        proposal_id = None
        if self.host.adapter.mutating(action) and self.confirmation is not None:
            proposal = self.host.prepare(action, arguments)
            self.host.confirm(proposal.id, self.confirmation(proposal))
            proposal_id = proposal.id
        return self.host.execute(action, arguments, proposal_id=proposal_id, request_id=request_id)

    def make_tool_call(self, tool_name, requestor="assistant", **kwargs):
        if requestor == "user":
            return self.host.adapter.user_action(self.host, tool_name, kwargs)
        if requestor != "assistant":
            raise ValueError("invalid requestor")
        result = self._assistant_call(tool_name, kwargs)
        if not result["allow"] or result.get("outcome") != "success":
            raise PermissionError(f"guardrail denied tool call: {result}")
        return result["result"]

    def use_tool(self, tool_name, **kwargs):
        return self.make_tool_call(tool_name, **kwargs)

    def use_user_tool(self, tool_name, **kwargs):
        return self.make_tool_call(tool_name, requestor="user", **kwargs)

    def get_response(self, message):
        from tau2.data_model.message import ToolMessage

        try:
            if message.requestor == "user":
                result = self.host.adapter.user_action(self.host, message.name, message.arguments)
            else:
                if message.requestor != "assistant":
                    raise ValueError("invalid requestor")
                result = self._assistant_call(message.name, message.arguments, message.id)
                if result.get("allow") and result.get("outcome") == "failure":
                    return ToolMessage(
                        id=message.id,
                        role="tool",
                        error=True,
                        content=f"Error: {result['error']}",
                        requestor=message.requestor,
                    )
                if not result["allow"] or result.get("outcome") != "success":
                    return ToolMessage(
                        id=message.id,
                        role="tool",
                        error=True,
                        content=wire_text(result),
                        requestor=message.requestor,
                    )
                result = result["result"]
            return ToolMessage(
                id=message.id,
                role="tool",
                error=False,
                content=wire_text(result),
                requestor=message.requestor,
            )
        except Exception as exc:  # noqa: BLE001 - transport boundary must fail closed
            return ToolMessage(
                id=message.id,
                role="tool",
                error=True,
                content=f"guardrail failure: {type(exc).__name__}",
                requestor=message.requestor,
            )
