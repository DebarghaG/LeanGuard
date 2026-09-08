"""Checks for the example adapter's trust and representation boundaries."""

import unittest
from copy import deepcopy

from leanguard import Engine, replay
from run import (
    HERE,
    SourceEvent,
    normalize,
    parse_trace,
    parse_value,
    provider_values,
    render_trace,
)

ALICE = 'Drupe::OAuthUser::"alice"'
GATEWAY = 'Drupe::Gateway::"gw1"'


def request(document="ABC"):
    return SourceEvent(
        0,
        "Read",
        "request",
        ALICE,
        GATEWAY,
        {"input": {"document": document, "user": "alice"}},
        {
            "input": {"document": document, "user": "alice"},
            "callerPrincipal": {"entity": ALICE},
            "callerResource": {"entity": GATEWAY},
        },
    )


class AdapterTests(unittest.TestCase):
    def test_quoted_delimiters_roundtrip(self):
        event = request('a), {b: [c]}, "quoted" \\ newline\n')
        self.assertEqual(parse_trace(render_trace([event])), [event])

    def test_duplicate_and_unsupported_values_rejected(self):
        for source in ("{x: 1, x: 2}", "{x: [1}", "bare_token", "0.00001"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_value(source)

    def test_decimal_exactness(self):
        self.assertEqual(parse_value("-0.0001"), {"decimal4": -1})
        self.assertEqual(parse_value("922337203685477.5807"), {"decimal4": 2**63 - 1})
        with self.assertRaises(ValueError):
            parse_value("922337203685477.5808")

    def test_context_and_logged_inputs_stay_separate(self):
        event = request()
        event.logged["input"]["document"] = "different"
        record = next(normalize("provider_regex_matches_uppercase", [event]))
        self.assertEqual(record["input"]["document"], "ABC")
        self.assertEqual(record["facts"]["logged"]["input"]["document"], "different")

    def test_inconsistent_scope_rejected(self):
        event = request()
        event.logged["callerPrincipal"] = {"entity": 'Drupe::OAuthUser::"bob"'}
        with self.assertRaisesRegex(ValueError, "authoritative scope"):
            list(normalize("read_after_login", [event]))

    def test_custom_kind_requires_declared_mapping(self):
        event = request()
        event.kind = "attempt"
        event.logged = {"input": event.logged["input"], "actor": {"entity": ALICE}}
        with self.assertRaisesRegex(ValueError, "unsupported source kind"):
            list(normalize("read_after_login", [event]))
        self.assertEqual(next(normalize("login_attempt_custom_kind", [event]))["kind"], "request")

    def test_regex_does_not_allow_trailing_newline(self):
        name = "provider_regex_matches_uppercase"
        self.assertTrue(provider_values(name, request("ABC"))["matched"])
        self.assertFalse(provider_values(name, request("ABC\n"))["matched"])

    def test_entity_id_containing_namespace_separator(self):
        event = request()
        event.principal = 'Drupe::OAuthUser::"alice::admin"'
        event.logged["callerPrincipal"] = {"entity": event.principal}
        record = next(normalize("provider_principal_id_allowlist", [event]))
        self.assertEqual(record["facts"]["principal_type"], "Drupe::OAuthUser")
        self.assertFalse(record["facts"]["providers"]["principal_allowed"])

    def test_missing_provider_result_fails_closed_in_native_engine(self):
        name = "provider_regex_matches_uppercase"
        event = next(normalize(name, [request()]))
        with Engine(name, binary=HERE / ".lake/build/bin/dogwood-guide") as engine:
            self.assertTrue(next(replay(engine, [event]))["decision"]["allow"])
            missing = deepcopy(event)
            missing["facts"]["providers"] = {}
            result = next(replay(engine, [missing]))
            self.assertFalse(result["decision"]["allow"])
            self.assertEqual(result["assessment"], "insufficient_evidence")
            self.assertTrue(result["decision"]["errors"])


if __name__ == "__main__":
    unittest.main()
