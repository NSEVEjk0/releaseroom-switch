# ReleaseRoom

**Ask for a page change in your team’s Switch room. Review the actual artifact. Approve exactly what gets released.**

ReleaseRoom turns a small content request into a checked staging release through three Switch roles: builder, tester and release agent. The person stays in chat while a release desk shows the diff, Git commit, independent checks and artifact fingerprint. A later change invalidates the earlier approval.

Useful for community landing pages, launch teams and internal announcements where “approved” should mean a particular checked revision, rather than whichever file happens to exist when a bot publishes it.

## Try the recorded example

Open the [ReleaseRoom desk](https://releaseroom-switch.vercel.app). The [verification run](https://github.com/NSEVEjk0/releaseroom-switch/actions/runs/41944197715) includes state/recovery tests, an actual local WebSocket/HTTP protocol fixture, and desktop/mobile browser checks.

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
4. Set the variables in `.env.example` in the service environment. Put the Vultr inference key and team access code in private files, never in frontend configuration. The builder is bounded to eight calls/day, 1,200 output tokens/call and one attempt per request. Model: Vultr `glm-5.3-flash`.
5. Run `python3 -m releaseroom.cli doctor`, then run `python3 -m releaseroom.cli serve` and `python3 -m releaseroom.cli run` as supervised processes. Serve the controller behind HTTPS and keep its state directory persistent. Set `RELEASEROOM_ORIGIN` to that exact public address.

In chat, address the builder with:

```text
[releaseroom] request Make the invitation say Join the build night.
```

The tester and release agent exchange authenticated targeted handoffs. The release role posts the exact `approve <release-id> <full-fingerprint>` instruction to the review thread. A configured human sends that instruction to the release agent. The resulting page is available at `/staging`, with an artifact-hash response header. The desk is read-only; its access code cannot grant release authority.

## Disconnection and recovery

Connections preserve UUID, cursor and generation; pongs continue during model calls. Addressed messages are stored durably and deduplicated. Other-room and unaddressed events cannot request work. A takeover permanently stops that connection. Missing room context or a gap blocks approval and publication. Failed context reads are visible in `doctor` without exposing keys.

Stop workers before recovery commands; an exclusive worker lock enforces this. Run `python3 -m releaseroom.cli recover` to reset interrupted publications to a fresh human approval. An expired approval is never exposed by recovery. The previous published staging pointer is restored where present. Run `resync <complete-context.json>` only after reading the recovered room history (`truncated: false`); it invalidates pending revisions and requires a new request. Restart workers so their in-memory context matches the recovered state. Messages interrupted in-flight are marked uncertain and are not automatically repeated as paid model calls.

## Verification

The CI workflow runs state, tamper, expiry, recovery, identity and protocol tests; a real local WebSocket/HTTP protocol test with a disclosed scripted builder; `git fsck --strict`; reference generation; and desktop/mobile browser checks. The local protocol server is a fixture, not a live Switch service.

```sh
pip install -r requirements.txt
python3 -m unittest tests.test_core tests.test_protocol tests.test_setup tests.test_socket -v
npm install
npx playwright install chromium
npm run test:browser
```

The current scope is **bounded site-content staging**, not arbitrary repository changes or production infrastructure deployment. A completed Switch hackathon demonstration still needs a real authenticated person/agent conversation and configured model/controller. MIT applies to ReleaseRoom’s own code; Switch and provider services retain their own terms.
