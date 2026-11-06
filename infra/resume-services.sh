#!/usr/bin/env bash
set -euo pipefail
releaseroom_project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$releaseroom_project"
if [[ $EUID -ne 0 ]]; then
  printf '%s\n' 'Run this from the ordinary VPS root terminal.' >&2
  exit 1
fi
releaseroom_python="$releaseroom_project/.local/vps/venv/bin/python"
if [[ ! -f .local/vps/bootstrap.json || ! -x "$releaseroom_python" ]]; then
  printf '%s\n' 'Complete the initial start-local.sh setup first.' >&2
  exit 1
fi
"$releaseroom_python" -c 'from releaseroom.vps import repair_service_working_directories; print({"repaired_services":repair_service_working_directories()})'
# This fixture check makes no model calls and sends no Switch messages.
RELEASEROOM_UI_FIXTURES=1 node node_modules/playwright/cli.js test tests/browser/live-desk.spec.ts --reporter=line
mapfile -t releaseroom_units < <("$releaseroom_python" -c 'import json; from pathlib import Path; p=Path(".local/vps"); c=json.loads((p/"config.json").read_text()); print("releaseroom-desk.service\nreleaseroom-workers.service"); print("shortlist.service") if c.get("shortlist") else None')
for releaseroom_unit in "${releaseroom_units[@]}"; do
  if [[ $(readlink -f -- "/etc/systemd/system/$releaseroom_unit") != "$releaseroom_project/.local/vps/$releaseroom_unit" ]]; then
    printf '%s\n' 'An installed service differs from this prepared deployment; existing host files were kept.' >&2
    exit 1
  fi
done
systemctl daemon-reload
systemctl reset-failed "${releaseroom_units[@]}"
systemctl enable "${releaseroom_units[@]}"
systemctl restart "${releaseroom_units[@]}"
"$releaseroom_python" -c 'import json; from pathlib import Path; from releaseroom.vps import PORTS,wait_json; from releaseroom.setup import private_json; p=Path(".local/vps"); c=json.loads((p/"config.json").read_text()); s=wait_json("http://127.0.0.1:"+str(PORTS["desk"])+"/api/config",timeout=45,predicate=lambda x:x.get("available")); wait_json("http://127.0.0.1:"+str(PORTS["shortlist"])+"/_agent-native/health",timeout=10) if c.get("shortlist") else None; c["status"]="services started; actual human demonstration still required"; private_json(p/"config.json",c); print({"releaseroom_connected":s["available"],"shortlist_started":bool(c.get("shortlist")),"human_demo":"required"})'
