"""Enroll ReleaseRoom on an operator's Switch server; never simulate a person."""
from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .http_client import NoRedirect, SwitchHTTP
from .protocol import ConnectionState
from .setup import private_json, resolve_profiles, validate_profiles
from .store import Store

ROLES = ("builder", "tester", "release")
ROOM_NAME = "ReleaseRoom launch review"


class GatewayHTTP:
    def __init__(self, base: str):
        parsed = urlsplit(base)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use the Switch server base URL without credentials.")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("Remote Switch setup requires HTTPS.")
        self.base = base.rstrip("/")
        self.opener = build_opener(NoRedirect(), HTTPCookieProcessor(CookieJar()))

    def request(self, path: str, body=None, *, method=None, bearer=None):
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        request = Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                          headers=headers, method=method or ("GET" if body is None else "POST"))
        try:
            with self.opener.open(request, timeout=20) as response:
                data = response.read(1_048_577)
        except HTTPError as error:
            # Server error bodies can contain account details. Keep them private.
            raise ValueError(f"Switch setup request {path} failed with HTTP {error.code}.") from None
        if len(data) > 1_048_576:
            raise ValueError("Switch setup response exceeds the supported size.")
        return json.loads(data)


def enroll_roles(gateway, folder: Path):
    profile_file = folder / "switch-agents.json"
    profiles = json.loads(profile_file.read_text()) if profile_file.exists() else {}
    if not isinstance(profiles, dict) or set(profiles) - set(ROLES):
        raise ValueError("The saved agent file has unexpected roles.")
    key_file = folder / "registration.json"
    registration = json.loads(key_file.read_text()) if key_file.exists() else None
    if len(profiles) != 3 and registration is None:
        registration = gateway.request("/gateway/api-keys", {"label": "ReleaseRoom enrollment"})
        if not isinstance(registration.get("key"), str) or not registration["key"]:
            raise ValueError("Switch did not return the enrollment key.")
        private_json(key_file, registration)
    for role in ROLES:
        if role in profiles:
            if any(not isinstance(profiles[role].get(k), str) or not profiles[role][k] for k in ("id", "api_key", "name")):
                raise ValueError("A saved agent profile is incomplete; recover it in Switch before retrying.")
            continue
        name = "releaseroom-" + role
        response = gateway.request("/agents", {
            "name": name, "display_name": "ReleaseRoom " + role,
            "description": {"builder": "Proposes bounded announcement content with the configured model.",
                            "tester": "Independently checks and pins the proposed content.",
                            "release": "Publishes only the exact artifact approved by the configured person."}[role],
            "connector_type": "releaseroom",
            "integration_profile": {"connection_model": "always_on", "message_exchange": True,
                                    "pre_invocation_mediation": [], "post_invocation_mediation": [], "event_reporting": []},
            "overwrite": False,
        }, bearer=registration["key"])
        if any(not isinstance(response.get(k), str) or not response[k] for k in ("id", "api_key")):
            raise ValueError("Switch did not return an agent identity and key.")
        profiles[role] = {"id": response["id"], "api_key": response["api_key"], "name": name}
        # Save each one-time key before attempting another registration.
        private_json(profile_file, profiles)
    return profiles


def ensure_room(gateway, folder: Path, profiles, reviewer_name: str):
    room_file = folder / "room.json"
    ids = {p["id"] for p in profiles.values()}
    if room_file.exists():
        saved = json.loads(room_file.read_text())
        room = gateway.request("/gateway/rooms/" + quote(saved["id"], safe=""))
    else:
        rooms = gateway.request("/gateway/rooms")
        if not isinstance(rooms, list):
            raise ValueError("Switch returned an unexpected room list.")
        matches = [r for r in rooms if r.get("name") == ROOM_NAME]
        if len(matches) > 1:
            raise ValueError("Several rooms share the setup name; choose one in Switch before retrying.")
        if matches:
            room = gateway.request("/gateway/rooms/" + quote(matches[0]["id"], safe=""))
        else:
            room = gateway.request("/gateway/rooms", {
                "name": ROOM_NAME, "description": "Request, check, review and release a build-night announcement.",
                "agent_ids": [profiles[r]["id"] for r in ROLES], "user_names": [reviewer_name],
                "channel_type": "channel_private", "internal_only": False,
                "read_visibility": "private", "write_visibility": "private",
                "instructions": "Address releaseroom-builder with [releaseroom] request, and releaseroom-release with the exact approval it supplies. Human approval is required. Only bounded site content may be released.",
            })
        private_json(room_file, {k: room[k] for k in ("id", "name", "bridge_id", "external_channel_id") if k in room})
    if not room.get("id") or not room.get("bridge_id") or not room.get("external_channel_id") or set(room.get("agent_ids", [])) != ids:
        raise ValueError("The room must contain these three agents and a real messaging-app channel.")
    return room


async def read_participants(base: str, folder: Path, profiles, room_id: str):
    """Keep three real authenticated sockets alive while reading room identities."""
    from websockets.asyncio.client import connect
    store = Store(folder / "bootstrap-connections", set())
    tasks, states, clients = [], [], []

    async def receive(socket, state, ready):
        try:
            async for raw in socket:
                frame = json.loads(raw)
                pong = state.frame(frame)
                if pong is not None:
                    await socket.send(json.dumps(pong))
                if frame.get("event", frame.get("type")) == "connection_state":
                    ready.set()
        finally:
            state.disconnected()
            ready.set()

    try:
        async with AsyncExitStack() as stack:
            for role in ROLES:
                profile = profiles[role]
                state = ConnectionState(store, profile["id"], room_id)
                if state.halted:
                    raise ValueError("A setup connection was taken over; inspect it before retrying.")
                client = SwitchHTTP(base, profile["id"], profile["api_key"], state.connection_id)
                await asyncio.to_thread(client.discover)
                socket = await stack.enter_async_context(connect(state.url(base), additional_headers={"Authorization": "Bearer " + profile["api_key"]},
                                                                  max_size=1_048_576, ping_interval=None, open_timeout=20))
                ready = asyncio.Event()
                task = asyncio.create_task(receive(socket, state, ready))
                tasks.append(task)
                states.append(state)
                await asyncio.wait_for(ready.wait(), 20)
                if task.done():
                    await task
                if not state.connected or state.gapped:
                    raise ValueError("Switch did not provide a complete, live setup connection.")
                await asyncio.to_thread(client.op, "connect_to_room", {"room_id": room_id})
                clients.append(client)
            participants = await asyncio.to_thread(clients[0].op, "list_participants", {})
            if not all(state.connected and not state.gapped for state in states):
                raise ValueError("A setup connection became unavailable while resolving identities.")
            return participants
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def choose_reviewer(profiles, participants, name: str):
    resolved, humans = resolve_profiles(profiles, participants)
    matches = [h for h in humans if h["name"] == name]
    if len(matches) == 1:
        human = matches[0]
    elif len(humans) == 1:
        human = humans[0]
    else:
        raise ValueError("The real room must identify one unambiguous human reviewer.")
    validate_profiles(resolved, {human["id"]})
    return resolved, human


def bootstrap(base: str, folder: Path):
    credentials = json.loads((folder / "operator.json").read_text())
    gateway = GatewayHTTP(base)
    gateway.request("/gateway/auth/login", {"email": credentials["GATEWAY_ADMIN_EMAIL"], "password": credentials["GATEWAY_ADMIN_PASSWORD"]})
    profiles = enroll_roles(gateway, folder)
    room = ensure_room(gateway, folder, profiles, credentials["MATTERMOST_USER"])
    policy = {"rules": [{"rooms": [room["id"]], "users": [], "agents": [], "owner": True, "owner_agents": True}]}
    for role in ROLES:
        gateway.request("/gateway/agents/" + quote(profiles[role]["id"], safe="") + "/addressing-policy", {"policy": policy}, method="PUT")
    participants = asyncio.run(read_participants(base, folder, profiles, room["id"]))
    resolved, human = choose_reviewer(profiles, participants, credentials["MATTERMOST_USER"])
    private_json(folder / "switch-agents.json", resolved)
    private_json(folder / "participants.json", participants)
    private_json(folder / "bootstrap.json", {"room_id": room["id"], "reviewer_id": human["id"],
                                             "agent_ids": {r: resolved[r]["id"] for r in ROLES},
                                             "evidence": "live authenticated setup; no human task or model call yet"})
    return room["id"], human["id"]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("folder", type=Path)
    arguments = parser.parse_args()
    try:
        bootstrap(arguments.base, arguments.folder)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error) if isinstance(error, ValueError) else "Switch setup could not connect; inspect the local services.") from None
    print("Three Switch profiles and the room's actual human identity were resolved. A real human task and model run are still required.")
