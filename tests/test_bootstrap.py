import json
import tempfile
import unittest
from pathlib import Path

from releaseroom.bootstrap import GatewayHTTP, choose_reviewer, enroll_roles, ensure_room, ROOM_NAME


class GatewayFixture:
    """Scripted control-plane responses, never a live Switch service."""
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def request(self, path, body=None, **options):
        self.calls.append((path, body, options))
        if path == "/gateway/api-keys":
            return {"key": "fixture-registration"}
        if path == "/agents":
            if body["name"].endswith(self.fail or "never"):
                raise ValueError("fixture interruption")
            return {"id": body["name"] + "-server", "api_key": "fixture-key-" + body["name"]}
        if path == "/gateway/rooms" and body is None:
            return []
        if path == "/gateway/rooms":
            return {"id": "fixture-room", "name": ROOM_NAME, "bridge_id": "fixture-bridge", "external_channel_id": "fixture-channel", "agent_ids": body["agent_ids"]}
        raise AssertionError(path)


class BootstrapTests(unittest.TestCase):
    def test_interrupted_enrollment_preserves_one_time_keys_and_never_overwrites_agents(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with self.assertRaises(ValueError):
                enroll_roles(GatewayFixture(fail="tester"), folder)
            original = json.loads((folder / "switch-agents.json").read_text())["builder"]
            gateway = GatewayFixture()
            profiles = enroll_roles(gateway, folder)
            self.assertEqual(profiles["builder"], original)
            self.assertEqual([body["name"] for path, body, _ in gateway.calls if path == "/agents"], ["releaseroom-tester", "releaseroom-release"])
            self.assertFalse(any(path == "/gateway/api-keys" for path, _, _ in gateway.calls))
            self.assertTrue(all(body["overwrite"] is False for path, body, _ in gateway.calls if path == "/agents"))
            self.assertEqual((folder / "switch-agents.json").stat().st_mode & 0o777, 0o600)

    def test_room_is_private_bridged_and_contains_the_configured_human(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            gateway = GatewayFixture()
            profiles = enroll_roles(gateway, folder)
            room = ensure_room(gateway, folder, profiles, "reviewer")
            body = next(body for path, body, _ in gateway.calls if path == "/gateway/rooms" and body)
            self.assertEqual(body["user_names"], ["reviewer"])
            self.assertFalse(body["internal_only"])
            self.assertEqual(body["read_visibility"], "private")
            self.assertEqual(set(room["agent_ids"]), {p["id"] for p in profiles.values()})

    def test_reviewer_is_resolved_from_a_user_record_and_ambiguity_fails(self):
        profiles = {r: {"id": r + "-server", "api_key": "fixture", "name": r} for r in ("builder", "tester", "release")}
        participants = [{"id": "opaque-" + r, "name": r, "type": "agent"} for r in profiles]
        with self.assertRaises(ValueError):
            choose_reviewer(profiles, participants, "reviewer")
        participants.append({"id": "opaque-person", "name": "reviewer", "type": "user"})
        _, human = choose_reviewer(profiles, participants, "reviewer")
        self.assertEqual(human["id"], "opaque-person")
        participants.append({"id": "other-person", "name": "reviewer", "type": "user"})
        with self.assertRaises(ValueError):
            choose_reviewer(profiles, participants, "reviewer")

    def test_remote_setup_does_not_send_credentials_over_plain_http(self):
        with self.assertRaises(ValueError):
            GatewayHTTP("http://other-host.example")
        with self.assertRaises(ValueError):
            GatewayHTTP("https://user:password@switch.example")
        self.assertEqual(GatewayHTTP("http://127.0.0.1:18000").base, "http://127.0.0.1:18000")
