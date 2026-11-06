# ReleaseRoom

**Ask for a page change in your team’s Switch room. Review the actual artifact. Approve exactly what gets released.**

ReleaseRoom turns a small content request into a checked staging release through three Switch roles: builder, tester and release agent. The person stays in chat while a release desk shows the diff, Git commit, independent checks and artifact fingerprint. A later change invalidates the earlier approval.

Useful for community landing pages, launch teams and internal announcements where “approved” should mean a particular checked revision, rather than whichever file happens to exist when a bot publishes it.

## Problem and solution

A team approves one version in chat, then a later edit changes what the agent publishes. ReleaseRoom makes that mismatch observable and blocks it: builder, independent tester and release agent exchange work through Switch, while a human approves the full fingerprint of the reviewed revision. The live desk shows all six content fields, checks, revision history and downloadable evidence; it copies an approval command without sending it on the human's behalf.

## Try the recorded example

Open the [ReleaseRoom desk](https://releaseroom-switch.vercel.app). The [verification run](https://github.com/NSEVEjk0/releaseroom-switch/actions/runs/41949436382) includes state/recovery tests, an actual local WebSocket/HTTP protocol fixture, and desktop/mobile browser checks.

The public desk contains a **recorded local example**, produced by this release engine with a fictional reviewer. It demonstrates an actual generated Git artifact, stale approval rejection and staging publication. It has no live Switch conversation or AI call. The live board requires a configured controller and team access; the public preview cannot approve or publish releases.

```sh
python3 -m unittest tests.test_core tests.test_protocol tests.test_setup -v
RELEASEROOM_DEMO_DIR=/tmp/releaseroom-example python3 -m releaseroom.cli demo reports/reference-release.json
python3 -m releaseroom.cli verify reports/reference-release.json
git --git-dir=/tmp/releaseroom-example/artifact.git fsck --strict
```

Use an empty demo directory for a new reference. Expected output includes `"verified": true` and `"environment": "scripted-local-reference-no-Switch-no-AI"`. The earlier release is superseded; its approved fingerprint cannot publish the changed content. Verification checks reference integrity; it does not establish that an external person approved it.

## What approval binds

One full SHA256 fingerprint binds the release ID, current revision, reproducible Git commit, artifact, JSON source, checker implementation/policy, test evidence and original request. The publisher rechecks all bindings, current room health, human reviewer permission and the 15-minute expiry immediately before publishing. It verifies the pinned Git objects as well as the rendered HTML.

The builder proposes only six bounded JSON fields. The tester owns the schema, text limits, literal colors, WCAG 4.5 contrast check and three permitted local CTA destinations. Content is escaped into a fixed static renderer. Model text is never a shell command, deployment destination or approval.

```mermaid
flowchart LR
  H[Human in Switch] --> B[Builder proposes JSON]
  B --> T[Tester checks and commits artifact]
  T --> R[Release agent asks for exact approval]
  H --> R
  R --> S[Checked staging artifact]
```

Only the builder uses a model. Tester and publisher are deterministic agents with separate authenticated Switch identities. They share this controlled deployment process; they are not a hardware security boundary against the machine’s administrator.

## Connect an actual Switch room

Use Python 3.12+ and install `pip install -r requirements.txt`. The integration follows the current [Switch WebSocket + HTTP protocol](https://docs.switchagents.ai/switch-rooms/internals/agent-protocol), inspected at source revision `59d1f569ffb84f5fc66e2b6aa6a177619550f1a6`.

1. Register three agents once through your Switch administrator and add them to the same room as the human. Preserve their returned keys. Enable addressing between the configured owner’s agents and ensure human requests are addressed to the builder and approvals to the release role.
2. Create a protected JSON file with exactly `builder`, `tester`, `release` keys. Each profile has `id` (server agent ID), `api_key`, `name` (exact room agent name), and `participant_id` (opaque room identity).
3. Obtain the actual `list_participants` response after connecting to the room. `python3 -m releaseroom.cli resolve-profiles participants.json` resolves agent names to exact opaque IDs and lists human candidates. Choose the human’s returned `type: user` ID for `RELEASEROOM_REVIEWERS` and requesters. Do not derive IDs from display names, handles or Matrix strings.
4. Set the variables in `.env.example` in the service environment. Store the selected model key and team access code in private files. The builder supports NEAR AI (`z-ai/glm-5.3-flash`) and Vultr (`glm-5.3-flash`), with eight calls/day, 1,200 output tokens/call and one attempt per request. Request content leaves the controller for that configured provider when the builder runs.
5. Run `python3 -m releaseroom.cli doctor`, then run `python3 -m releaseroom.cli serve` and `python3 -m releaseroom.cli run` as supervised processes. Serve the controller behind HTTPS and keep its state directory persistent. Set `RELEASEROOM_ORIGIN` to that exact public address.

In chat, address the builder with:

```text
[releaseroom] request Make the invitation say Join the build night.
```

The tester and release agent exchange authenticated targeted handoffs. The release role posts the exact `approve <release-id> <full-fingerprint>` instruction to the review thread. A configured human sends that instruction to the release agent. The resulting page is available at `/staging`, with an artifact-hash response header. The desk is read-only; its access code cannot grant release authority.

## Prepare a bounded VPS deployment

The launcher uses the pinned Switch 0.31.0 deployment contract, bundled Mattermost, persistent Docker volumes and separate supervised desk/worker processes. An optional sibling Shortlist workspace shares PostgreSQL through its own role and database. It keeps credentials in `.local/vps/` with private file permissions and preserves them across reruns.

From this repository, prepare with a private file containing `NEAR_AI_API_KEY` and optionally `NEAR_AI_MODEL`:

```sh
python3 -m releaseroom.vps prepare --model-env /path/to/private-model.env --shortlist ../shortlist
python3 -m releaseroom.vps preflight
python3 -m releaseroom.vps start
```

Omit `--shortlist` for ReleaseRoom alone. For a standalone Vultr model key file, use `--model-key /path/to/private-key.txt --provider vultr` instead of `--model-env`. This provider choice applies to ReleaseRoom; ReproLab retains its own mandatory Vultr hosting and inference requirements.

Run `start` from the ordinary VPS root terminal with Docker Compose and systemd available. The launcher checks model access without generation, inspects image sizes before pulling, reserves 8 GiB of free disk plus a dependency allowance, requires 1 GiB of available RAM and applies container/process memory and log limits. It runs backend checks and Shortlist's isolated database, build and browser checks before enabling application services. Failed checks stop launch. Actual startup and a real human demonstration still need verification on the host.

All services bind to loopback. Forward ports `13000` (Switch Gateway), `18000` (Switch API), `18065` (Mattermost), `18090` (ReleaseRoom desk) and optionally `18173` (Shortlist) over SSH, using the same local port numbers. Open the corresponding `http://localhost:<port>` addresses. Gateway and Mattermost login values are in the private `operator.json`; the desk access code is in `team-access.txt`. The launcher resolves reviewer IDs from real authenticated room participants after messaging setup completes.

`python3 -m releaseroom.vps status` reports the saved configuration. Preparation creates files; a successful start is followed by an actual request, stale-approval rejection and fresh human-approved release for the demonstration. Public HTTPS exposure can then be configured with the chosen domain and exact origins.

If the initial installation finished enrolling the room but stopped at service startup, run `bash infra/resume-services.sh` from the ordinary VPS root terminal. It repairs the recognized earlier working-directory syntax, verifies the installed unit links, reloads only the prepared application services and checks readiness. It does not repeat dependency installation, replace keys or reset databases. The actual human conversation remains required.

## Disconnection and recovery

Connections preserve UUID, cursor and generation; pongs continue during model calls. Addressed messages are stored durably and deduplicated. Other-room and unaddressed events cannot request work. A takeover permanently stops that connection. Missing room context or a gap blocks approval and publication. Failed context reads are visible in `doctor` without exposing keys.

Stop workers before recovery commands; an exclusive worker lock enforces this. Run `python3 -m releaseroom.cli recover` to reset interrupted publications to a fresh human approval. An expired approval is never exposed by recovery. The previous published staging pointer is restored where present. Run `resync <complete-context.json>` only after reading the recovered room history (`truncated: false`); it invalidates pending revisions and requires a new request. Restart workers so their in-memory context matches the recovered state. Messages interrupted in-flight are marked uncertain and are not automatically repeated as paid model calls.

## Verification

The CI workflow runs state, tamper, expiry, recovery, identity and protocol tests; a real local WebSocket/HTTP protocol test with a disclosed scripted builder; `git fsck --strict`; reference generation; and desktop/mobile browser checks. The local protocol server is a fixture, not a live Switch service.

```sh
pip install -r requirements.txt
python3 -m unittest tests.test_core tests.test_protocol tests.test_setup tests.test_provider tests.test_storage tests.test_bootstrap tests.test_vps tests.test_socket -v
npm ci --no-audit --no-fund
npx playwright install chromium
npm run test:browser
```

The current scope is **bounded site-content staging**, not arbitrary repository changes or production infrastructure deployment. A completed Switch hackathon demonstration still needs a real authenticated person/agent conversation and configured model/controller. MIT applies to ReleaseRoom’s own code; Switch and provider services retain their own terms.

See [submission and demo preparation](SUBMISSION.md) for the real human workflow, recording outline and remaining entry steps.
