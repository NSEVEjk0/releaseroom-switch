"""Prepare or start the bounded VPS deployment from an ordinary host terminal."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .bootstrap import bootstrap
from .http_client import NoRedirect
from .provider import BuilderProvider, PROVIDERS
from .setup import operator_lock, private_json, resolve_sender_ids, validate_profiles

PROJECT = Path(__file__).resolve().parent.parent
GIB = 1024 ** 3
COMPOSE_SHA256 = "e645d53b2d2df9fe7b1be183bc2801ec32e07fe1c79b44bf1f4386ce8b6e815e"
PORTS = {"api": 18000, "gateway": 13000, "chat": 18065, "desk": 18090, "database": 15439, "shortlist": 18173}
MIN_AVAILABLE_MEMORY = GIB
SOCKET_WHEEL_SHA256 = "c6bd2c9781915592b209160d0f017d4c7c82ad53075e6b0c24d2a89299e7f9e9"


def private_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_env(path: Path):
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.removeprefix("export ").split("=", 1)
        parts = shlex.split(value, comments=True)
        result[name.strip()] = parts[0] if len(parts) == 1 else value.strip()
    return result


def environment_text(values):
    lines = []
    for name, value in values.items():
        value = str(value)
        if any(c in value for c in "\r\n\x00"):
            raise ValueError("Environment values must be single-line strings.")
        lines.append(name + '="' + value.replace("\\", "\\\\").replace('"', '\\"') + '"')
    return "\n".join(lines) + "\n"


def repair_shortlist_engine_setting(peer):
    """Correct the earlier JSON-array env value while preserving all other bytes."""
    path = Path(peer) / ".local/vps.env"
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("Use Shortlist's regular private VPS environment file.")
    original = path.read_bytes()
    if read_env(path).get("AGENT_BUILT_IN_ENGINES") != '["ai-sdk:openai"]':
        return False
    lines = original.decode().splitlines(keepends=True)
    pattern = re.compile(r"^([ \t]*(?:export[ \t]+)?AGENT_BUILT_IN_ENGINES[ \t]*=)")
    matches = [(index, pattern.match(line)) for index, line in enumerate(lines) if pattern.match(line)]
    if len(matches) != 1:
        raise ValueError("The Shortlist engine setting is ambiguous; existing configuration was kept.")
    index, match = matches[0]
    ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
    lines[index] = match.group(1) + '"ai-sdk:openai"' + ending
    if path.read_bytes() != original:
        raise ValueError("The Shortlist configuration changed during repair; existing configuration was kept.")
    private_text(path, "".join(lines))
    return True


def unit_argument(value):
    if any(c in str(value) for c in "\r\n\x00"):
        raise ValueError("Service arguments must stay on one line.")
    return '"' + str(value).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def unit_working_directory(value):
    # WorkingDirectory and EnvironmentFile accept a literal path, unlike
    # ExecStart's word list. Use this for both path directives.
    # Surrounding quotes become part of the path and systemd rejects it.
    path = str(value)
    if not Path(path).is_absolute() or any(c in path for c in "\r\n\x00"):
        raise ValueError("Use an absolute single-line service path.")
    return path.replace("%", "%%")


def repair_service_working_directories(project=PROJECT):
    """Repair recognized generated path directives; keep operator edits intact."""
    project = Path(project).resolve()
    folder = project / ".local/vps"
    config = json.loads((folder / "config.json").read_text())
    directories = {"releaseroom-desk.service": project, "releaseroom-workers.service": project}
    if config.get("shortlist"):
        directories["shortlist.service"] = Path(config["shortlist"])
    changed = []
    for name, directory in directories.items():
        path = folder / name
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("Use the regular private prepared service files; no service was replaced.")
        original = path.read_bytes()
        replacements = [("WorkingDirectory=" + unit_argument(directory) + "\n",
                         "WorkingDirectory=" + unit_working_directory(directory) + "\n")]
        if name.startswith("releaseroom-"):
            replacements.extend(("EnvironmentFile=" + unit_argument(folder / filename) + "\n",
                                 "EnvironmentFile=" + unit_working_directory(folder / filename) + "\n")
                                for filename in ("app.env", "runtime.env"))
        repaired = original
        for old, new in replacements:
            if repaired.count(old.encode()) == 1:
                repaired = repaired.replace(old.encode(), new.encode())
        if repaired != original:
            if path.read_bytes() != original:
                raise ValueError("A service file changed during repair; the operator edit was kept.")
            private_text(path, repaired.decode())
            changed.append(name)
    return changed


def service_unit(description, command, working_directory, environment_files, writable, memory):
    return "\n".join([
        "[Unit]", "Description=" + description, "After=network-online.target docker.service", "Wants=network-online.target",
        "StartLimitIntervalSec=60", "StartLimitBurst=3", "", "[Service]", "Type=simple",
        "WorkingDirectory=" + unit_working_directory(working_directory),
        *("EnvironmentFile=" + unit_working_directory(p) for p in environment_files),
        "ExecStart=" + " ".join(unit_argument(p) for p in command),
        "Restart=on-failure", "RestartSec=5", "NoNewPrivileges=true", "PrivateTmp=true", "ProtectSystem=strict",
        "ProtectHome=read-only", "ReadWritePaths=" + unit_argument(writable), "MemoryMax=" + memory,
        "", "[Install]", "WantedBy=multi-user.target", "",
    ])


def prepare(project=PROJECT, *, model_env=None, model_key=None, provider="nearai", model=None, shortlist=None):
    project = Path(project).resolve()
    folder = project / ".local/vps"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    folder.chmod(0o700)
    source = project / "infra/vendor/switch/compose.yml"
    if hashlib.sha256(source.read_bytes()).hexdigest() != COMPOSE_SHA256:
        raise ValueError("The pinned Switch deployment source has changed; review it before preparing services.")
    if (folder / "config.json").exists():
        config = json.loads((folder / "config.json").read_text())
        if shortlist and config.get("shortlist") != str(Path(shortlist).resolve()):
            raise ValueError("This deployment is already prepared; keep its saved project and credentials.")
        if config.get("shortlist"):
            repair_shortlist_engine_setting(config["shortlist"])
        repair_service_working_directories(project)
        return config
    if provider not in PROVIDERS:
        raise ValueError("Choose the supported nearai or vultr provider.")
    if model_env:
        values = read_env(Path(model_env))
        key = values.get("NEAR_AI_API_KEY", "")
        model = model or values.get("NEAR_AI_MODEL")
        provider = "nearai"
    elif model_key:
        key = Path(model_key).read_text().strip()
    else:
        raise ValueError("Supply a private model environment or key file for the first preparation.")
    if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError("The private model key is empty or invalid.")
    model = model or PROVIDERS[provider][1]
    BuilderProvider(None, provider=provider, model=model)  # Validate the model identifier without sending a request.
    operator_file = folder / "operator.json"
    credentials = json.loads(operator_file.read_text()) if operator_file.exists() else {
        "GATEWAY_ADMIN_EMAIL": "reviewer@releaseroom.local", "GATEWAY_ADMIN_PASSWORD": secrets.token_hex(24),
        "MATTERMOST_ADMIN_USER": "release-admin", "MATTERMOST_ADMIN_PASSWORD": secrets.token_hex(24),
        "MATTERMOST_USER": "reviewer", "MATTERMOST_USER_PASSWORD": secrets.token_hex(24),
        "DB_OWNER_PASSWORD": secrets.token_hex(24), "DB_PASSWORD": secrets.token_hex(24),
        "AGENT_REGISTRATION_TOKEN": secrets.token_hex(32), "SECRET_KEYS": "v1:" + secrets.token_hex(32),
        "SHORTLIST_DB_PASSWORD": secrets.token_hex(24), "SHORTLIST_AUTH_SECRET": secrets.token_hex(32),
    }
    private_json(operator_file, credentials)
    private_text(folder / "model-key.txt", key + "\n")
    private_text(folder / "team-access.txt", secrets.token_urlsafe(32) + "\n")
    (folder / "state").mkdir(exist_ok=True, mode=0o700)
    stack = {**credentials, "SWITCH_VERSION": "0.31.0", "COMPOSE_PROFILES": "collab,gateway", "SWITCH_BIND_ADDR": "127.0.0.1",
             "API_HOST_PORT": PORTS["api"], "GATEWAY_HOST_PORT": PORTS["gateway"], "MATTERMOST_HOST_PORT": PORTS["chat"],
             "POSTGRES_HOST_PORT": PORTS["database"], "DB_OWNER_USER": "switch_owner", "DB_USER": "switch_app", "DB_NAME": "switch",
             "MATTERMOST_TEAM_NAME": "releaseroom", "FRONTEND_BASE_URL": "http://localhost:" + str(PORTS["gateway"]),
             "GATEWAY_PUBLIC_URL": "http://localhost:" + str(PORTS["api"]), "GATEWAY_COOKIE_SECURE": "false",
             "TELEMETRY_ENABLED": "false", "THIRD_PARTY_AVATARS_ENABLED": "false"}
    private_text(folder / "stack.env", environment_text(stack))
    logging = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "2"}}
    services = {name: {"restart": "unless-stopped", "logging": logging, "mem_limit": memory}
                for name, memory in {"postgres": "256m", "mattermost": "512m", "switch": "768m", "gateway": "128m"}.items()}
    services["switch"]["environment"] = {"ID_SERVER_NAME": "releaseroom.local", "MATRIX_SERVER_NAME": "releaseroom.local"}
    services["setup"] = {"logging": logging, "mem_limit": "256m", "environment": {"MATTERMOST_PUBLIC_URL": "http://localhost:" + str(PORTS["chat"])}}
    services["init-db"] = {"logging": logging, "mem_limit": "128m"}
    private_json(folder / "compose.override.json", {"services": services})
    app_env = {"RELEASEROOM_STATE_DIR": str(folder / "state"), "RELEASEROOM_AGENT_FILE": str(folder / "switch-agents.json"),
               "RELEASEROOM_HOST": "127.0.0.1", "RELEASEROOM_PORT": PORTS["desk"], "RELEASEROOM_ORIGIN": "http://localhost:" + str(PORTS["desk"]),
               "RELEASEROOM_SWITCH_URL": "http://127.0.0.1:" + str(PORTS["api"]), "RELEASEROOM_MODEL_PROVIDER": provider,
               "RELEASEROOM_MODEL": model, "RELEASEROOM_MODEL_KEY_FILE": str(folder / "model-key.txt"),
               "RELEASEROOM_ACCESS_FILE": str(folder / "team-access.txt"), "PYTHONUNBUFFERED": "1"}
    private_text(folder / "app.env", environment_text(app_env))
    private_text(folder / "runtime.env", "# Real room and reviewer IDs are written after authenticated Switch setup.\n")
    python = folder / "venv/bin/python"
    for name, command in (("desk", "serve"), ("workers", "run")):
        private_text(folder / ("releaseroom-" + name + ".service"), service_unit("ReleaseRoom " + name,
                     [python, "-m", "releaseroom.cli", command], project, [folder / "app.env", folder / "runtime.env"], folder / "state", "256M"))
    shortlist_path = str(Path(shortlist).resolve()) if shortlist else None
    if shortlist_path:
        peer = Path(shortlist_path)
        peer_folder = peer / ".local"
        peer_folder.mkdir(exist_ok=True, mode=0o700)
        peer_env = {"DATABASE_URL": "postgres://shortlist_app:" + credentials["SHORTLIST_DB_PASSWORD"] + "@127.0.0.1:" + str(PORTS["database"]) + "/shortlist",
                    "BETTER_AUTH_SECRET": credentials["SHORTLIST_AUTH_SECRET"], "BETTER_AUTH_URL": "http://localhost:" + str(PORTS["shortlist"]),
                    "OPENAI_API_KEY": key, "OPENAI_BASE_URL": PROVIDERS[provider][0].removesuffix("/chat/completions"), "AGENT_MODEL": model,
                    "AGENT_ENGINE": "ai-sdk:openai", "AGENT_BUILT_IN_ENGINES": "ai-sdk:openai",
                    "AGENT_MAX_ITERATIONS": "8", "AGENT_MAX_RUN_INPUT_TOKENS": "32000",
                    "AGENT_MAX_OUTPUT_TOKENS": "1200", "AGENT_MAIN_CHAT_MAX_OUTPUT_TOKENS": "1200",
                    "AGENT_EMPTY_RESPONSE_RETRY_MAX_OUTPUT_TOKENS": "1200",
                    "SHORTLIST_SPONSORED_AI": "true", "SHORTLIST_DAILY_AI_LIMIT": "8", "SHORTLIST_USER_DAILY_AI_LIMIT": "4",
                    "HOST": "127.0.0.1", "PORT": PORTS["shortlist"], "NITRO_HOST": "127.0.0.1", "NITRO_PORT": PORTS["shortlist"],
                    "NODE_OPTIONS": "--max-old-space-size=512", "NITRO_PRESET": "node-server", "NODE_ENV": "production"}
        private_text(peer_folder / "vps.env", environment_text(peer_env))
        private_text(folder / "shortlist.service", service_unit("Shortlist private workspace", [shutil.which("npm") or "/usr/bin/npm", "run", "start"],
                     peer, [peer_folder / "vps.env"], peer, "768M"))
    config = {"project": str(project), "ports": PORTS, "provider": provider, "model": model, "shortlist": shortlist_path,
              "switch_version": "0.31.0", "status": "prepared; services have not been started"}
    # Written last: a failed preparation can resume without replacing saved passwords.
    private_json(folder / "config.json", config)
    return config


def run(arguments, *, environment=None, cwd=PROJECT, input=None, capture=False, check=True):
    return subprocess.run([str(a) for a in arguments], cwd=cwd, env=environment, input=input, text=True,
                          capture_output=capture, check=check)


def compose(project=PROJECT):
    folder = project / ".local/vps"
    return ["docker", "compose", "--project-name", "releaseroom-vps", "--project-directory", project,
            "--env-file", folder / "stack.env", "-f", project / "infra/vendor/switch/compose.yml", "-f", folder / "compose.override.json"]


def configure_sender_identities(project=PROJECT):
    """Read actual Switch client identities without guessing Matrix addresses."""
    project = Path(project).resolve()
    folder = project / ".local/vps"
    profiles = json.loads((folder / "switch-agents.json").read_text())
    evidence = json.loads((folder / "bootstrap.json").read_text())
    validate_profiles(profiles, {evidence["reviewer_id"]})
    sql = """SELECT json_build_object('participant_id', a.id, 'sender_id', c.matrix_user_id, 'type', 'agent')
FROM agents a JOIN clients c ON c.id=a.client_id AND c.tenant_id=a.tenant_id
WHERE a.id IN (SELECT jsonb_array_elements_text(:'agent_ids'::jsonb))
UNION ALL
SELECT json_build_object('participant_id', u.id, 'sender_id', c.matrix_user_id, 'type', 'user')
FROM external_users u JOIN clients c ON c.id=u.client_id AND c.tenant_id=u.tenant_id
WHERE u.id=:'reviewer_id';
"""
    result = run(compose(project) + ["exec", "-T", "postgres", "psql", "-U", "switch_owner", "-d", "switch",
                 "-t", "-A", "-v", "ON_ERROR_STOP=1", "-v",
                 "agent_ids=" + json.dumps([p["id"] for p in profiles.values()]),
                 "-v", "reviewer_id=" + evidence["reviewer_id"]], input=sql, capture=True)
    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    resolve_sender_ids(profiles, {evidence["reviewer_id"]}, records)
    private_json(folder / "sender-identities.json", records)
    return records


def require_space(reserve=8 * GIB):
    if shutil.disk_usage(PROJECT).free < reserve:
        raise ValueError("Setup stopped to preserve at least 8 GiB of free disk space.")


def require_memory():
    available = next((int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                      if line.startswith("MemAvailable:")), None)
    if available is None or available < MIN_AVAILABLE_MEMORY:
        raise ValueError("Setup stopped: less than 1 GiB of available RAM. Free memory before running the bounded stack.")
    return available


def inspect_download_budget(command, *, dependencies=0):
    images = set(run(command + ["config", "--images"], capture=True).stdout.splitlines())
    compressed = 0
    for image in sorted(images):
        if run(["docker", "image", "inspect", image], capture=True, check=False).returncode == 0:
            continue
        result = run(["docker", "manifest", "inspect", "--verbose", image], capture=True, check=False)
        if result.returncode:
            raise ValueError("Cannot inspect the pinned image " + image + "; no images were downloaded.")
        data = json.loads(result.stdout)
        sizes = []
        def collect(value):
            if isinstance(value, dict):
                if isinstance(value.get("layers"), list):
                    sizes.append(sum(layer.get("size", 0) for layer in value["layers"]))
                for child in value.values(): collect(child)
            elif isinstance(value, list):
                for child in value: collect(child)
        collect(data)
        if not sizes:
            raise ValueError("The image download size is unavailable; refusing an unbounded pull.")
        compressed += max(sizes)
    if compressed * 3 + dependencies + 8 * GIB > shutil.disk_usage(PROJECT).free:
        raise ValueError("The container stack exceeds the available disk budget; setup skipped before downloading images.")


def wait_json(url, timeout=180, predicate=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with build_opener(NoRedirect()).open(url, timeout=5) as response:
                result = json.loads(response.read(1_048_576))
                if predicate is None or predicate(result):
                    return result
        except (OSError, ValueError, URLError):
            pass
        time.sleep(2)
    raise ValueError("Timed out waiting for the local service at " + url)


def verify_model(folder, config):
    endpoint = PROVIDERS[config["provider"]][0].removesuffix("/chat/completions") + "/models"
    request = Request(endpoint, headers={"Authorization": "Bearer " + (folder / "model-key.txt").read_text().strip()})
    try:
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            data = response.read(1_048_577)
    except HTTPError as error:
        raise ValueError(f"The configured model service refused access (HTTP {error.code}); check the private key file.") from None
    if len(data) > 1_048_576 or config["model"] not in {r.get("id") for r in json.loads(data).get("data", [])}:
        raise ValueError("The configured model is not listed by the selected provider.")


def setup_shortlist(project, folder, config, command):
    if not config.get("shortlist"):
        return
    peer = Path(config["shortlist"])
    if repair_shortlist_engine_setting(peer):
        print("Corrected Shortlist's built-in engine selection; other saved configuration was preserved.")
    credentials = json.loads((folder / "operator.json").read_text())
    password = credentials["SHORTLIST_DB_PASSWORD"]
    if not password.isalnum():
        raise ValueError("The generated database password is invalid.")
    sql = "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='shortlist_app') THEN CREATE ROLE shortlist_app LOGIN PASSWORD '" + password + "'; END IF; END $$;\n"
    sql += "SELECT 'CREATE DATABASE shortlist OWNER shortlist_app' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='shortlist')\\gexec\n"
    sql += "SELECT 'CREATE DATABASE shortlist_test OWNER shortlist_app' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='shortlist_test')\\gexec\n"
    run(command + ["exec", "-T", "postgres", "psql", "-U", "switch_owner", "-d", "postgres", "-v", "ON_ERROR_STOP=1"], input=sql)
    environment = {**os.environ, **read_env(peer / ".local/vps.env")}
    # Build checks do not receive the real model credential and use a separate database.
    checks = {**environment, "DATABASE_URL": environment["DATABASE_URL"] + "_test", "OPENAI_API_KEY": "build-without-a-model-key",
              "BETTER_AUTH_URL": "http://127.0.0.1:4173",
              "SHORTLIST_SPONSORED_AI": "false", "NODE_OPTIONS": "--max-old-space-size=768"}
    if not (peer / "node_modules/.bin/agent-native").exists():
        require_space()
        arguments = ["npm", "ci", "--include=dev", "--no-audit", "--no-fund", "--fetch-retries=0", "--fetch-timeout=25000"]
        if (peer / ".local/npm-cache").is_dir():
            arguments.extend(["--cache", peer / ".local/npm-cache"])
        run(arguments, cwd=peer, environment=checks)
    pending_scripts = peer / ".local/install-scripts-pending.json"
    if pending_scripts.exists():
        require_space()
        run(["npm", "rebuild", "--offline", "--cache", peer / ".local/npm-cache"], cwd=peer, environment=checks)
        pending_scripts.unlink()
    for arguments in (["npm", "run", "migrate:production"], ["npm", "test"], ["npm", "run", "typecheck"],
                      ["npm", "run", "agent-native:doctor"], ["npm", "run", "build"]):
        require_space()
        run(arguments, cwd=peer, environment=checks)
    require_space()
    run(["npm", "exec", "--no", "--", "playwright", "install", "chromium", "--only-shell"], cwd=peer, environment=checks)
    run(["npm", "run", "test:browser"], cwd=peer, environment=checks)
    run(["npm", "run", "migrate:production"], cwd=peer, environment=environment)


def preflight(project=PROJECT):
    project = Path(project).resolve()
    config = json.loads((project / ".local/vps/config.json").read_text())
    require_space()
    available = require_memory()
    daemon = run(["docker", "info", "--format", "{{.ServerVersion}}"], capture=True, check=False)
    bus = run(["systemctl", "is-system-running"], capture=True, check=False)
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
        listening = True
    except OSError:
        listening = False
    systemd = "Failed to connect" not in bus.stderr and "Operation not permitted" not in bus.stderr and bool(bus.stdout.strip())
    return {"docker_access": daemon.returncode == 0, "systemd_access": systemd, "listening_allowed": listening,
            "free_disk_gib": round(shutil.disk_usage(project).free / GIB, 2),
            "available_ram_gib": round(available / GIB, 2), "shortlist_prepared": bool(config.get("shortlist")),
            "shortlist_install_scripts_pending": bool(config.get("shortlist") and (Path(config["shortlist"]) / ".local/install-scripts-pending.json").exists()),
            "services_started": config["status"].startswith("services started")}


def start(project=PROJECT):
    folder = project / ".local/vps"
    config = json.loads((folder / "config.json").read_text())
    repaired = repair_service_working_directories(project)
    if repaired:
        print("Corrected the prepared service working directories; saved accounts and keys were preserved.")
    if os.geteuid() != 0:
        raise ValueError("Start this deployment from the VPS root terminal.")
    require_space()
    require_memory()
    daemon = run(["docker", "info", "--format", "{{.ServerVersion}}"], capture=True, check=False)
    if daemon.returncode:
        raise ValueError("This session cannot access the Docker daemon. Run the start command in the ordinary VPS terminal.")
    bus = run(["systemctl", "is-system-running"], capture=True, check=False)
    if "Failed to connect" in bus.stderr or "Operation not permitted" in bus.stderr:
        raise ValueError("This session cannot access systemd. Run the start command in the ordinary VPS terminal.")
    command = compose(project)
    run(command + ["config", "--quiet"], capture=True)
    require_space()
    verify_model(folder, config)  # Read-only provider check; no paid generation.
    inspect_download_budget(command, dependencies=(2 * GIB if config.get("shortlist") else 256 * 1024 ** 2))
    images = sorted(set(run(command + ["config", "--images"], capture=True).stdout.splitlines()))
    for image in images:
        require_space()
        run(["docker", "pull", image])
    require_space()
    python = folder / "venv/bin/python"
    if not python.exists():
        run([sys.executable, "-m", "venv", folder / "venv"])
    installed = run([python, "-c", "import importlib.metadata; print(importlib.metadata.version('websockets'))"], capture=True, check=False)
    if installed.returncode or installed.stdout.strip() != "17.4":
        require_space()
        wheel = folder / "wheels/websockets-17.4-py3-none-any.whl"
        if wheel.exists():
            if hashlib.sha256(wheel.read_bytes()).hexdigest() != SOCKET_WHEEL_SHA256:
                raise ValueError("The retained socket dependency does not match its published hash.")
            run([python, "-m", "pip", "--disable-pip-version-check", "install", "--no-index", wheel])
        else:
            run([python, "-m", "pip", "--disable-pip-version-check", "install", "-r", project / "requirements.txt"])
    run([python, "-m", "unittest", "tests.test_core", "tests.test_protocol", "tests.test_setup", "tests.test_provider", "tests.test_storage", "tests.test_bootstrap", "tests.test_vps", "tests.test_socket", "-v"])
    run(command + ["up", "-d", "postgres", "init-db"])
    setup_shortlist(project, folder, config, command)
    run(command + ["up", "-d"])
    base = "http://127.0.0.1:" + str(PORTS["api"])
    wait_json(base + "/health")
    wait_json("http://127.0.0.1:" + str(PORTS["chat"]) + "/api/v4/system/ping")
    # Compose's seeder must finish linking the actual Mattermost account first.
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        result = run(command + ["ps", "--all", "--format", "json", "setup"], capture=True)
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()] if not result.stdout.lstrip().startswith("[") else json.loads(result.stdout)
        if rows and rows[0].get("State") == "exited" and rows[0].get("ExitCode") == 0:
            break
        time.sleep(2)
    else:
        raise ValueError("The Mattermost setup did not complete; inspect the setup container before retrying.")
    if not (folder / "bootstrap.json").exists():
        (folder / "state").mkdir(exist_ok=True)
        with operator_lock(folder / "state"):
            # The host interpreter need not have the socket dependency: use the prepared venv.
            run([python, "-m", "releaseroom.bootstrap", base, folder])
    profiles = json.loads((folder / "switch-agents.json").read_text())
    evidence = json.loads((folder / "bootstrap.json").read_text())
    validate_profiles(profiles, {evidence["reviewer_id"]})
    configure_sender_identities(project)
    private_text(folder / "runtime.env", environment_text({"RELEASEROOM_ROOM_ID": evidence["room_id"],
                 "RELEASEROOM_REVIEWERS": json.dumps([evidence["reviewer_id"]]), "RELEASEROOM_REQUESTERS": json.dumps([evidence["reviewer_id"]]),
                 "RELEASEROOM_IDENTITY_FILE": str(folder / "sender-identities.json")}))
    units = [folder / "releaseroom-desk.service", folder / "releaseroom-workers.service"]
    if config.get("shortlist"):
        units.append(folder / "shortlist.service")
    run(["systemctl", "link", *units])
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", *(p.name for p in units)])
    if config.get("shortlist"):
        wait_json("http://127.0.0.1:" + str(PORTS["shortlist"]) + "/_agent-native/health", timeout=60)
    status = wait_json("http://127.0.0.1:" + str(PORTS["desk"]) + "/api/config", timeout=30, predicate=lambda result: result.get("switch_connected"))
    if not status.get("switch_connected"):
        raise ValueError("The controller started but its three room connections are not ready; inspect the worker service.")
    config["status"] = "services started; actual human demonstration still required"
    private_json(folder / "config.json", config)
    print("Switch, ReleaseRoom" + (" and Shortlist" if config.get("shortlist") else "") + " started. Open the SSH-forwarded local addresses to perform the real human demo.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "start", "status", "preflight"))
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--model-env", type=Path)
    sources.add_argument("--model-key", type=Path)
    parser.add_argument("--provider", choices=tuple(PROVIDERS), default="nearai")
    parser.add_argument("--model")
    parser.add_argument("--shortlist", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            config = prepare(model_env=args.model_env, model_key=args.model_key, provider=args.provider, model=args.model, shortlist=args.shortlist)
            print(json.dumps({"prepared": True, "switch_version": config["switch_version"], "shortlist_prepared": bool(config["shortlist"]), "services_started": False}))
        elif args.command == "start":
            start()
        elif args.command == "preflight":
            print(json.dumps(preflight()))
        else:
            config = json.loads((PROJECT / ".local/vps/config.json").read_text())
            print(json.dumps({k: config[k] for k in ("ports", "provider", "model", "shortlist", "status")}))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        message = str(error) if isinstance(error, ValueError) else "VPS setup failed at " + type(error).__name__ + "; inspect the local service or dependency output."
        raise SystemExit(message) from None


if __name__ == "__main__":
    main()
