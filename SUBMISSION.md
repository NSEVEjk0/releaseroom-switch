# ReleaseRoom submission materials

**Track: Best Business Workflow. Submission closes 7 November 2026 at 18:29 UTC / 23:59 IST.**

The [official challenge](https://www.wemakedevs.org/hackathons/switch) asks for at least one person and one AI agent completing a real task through Switch. It judges central Switch use, technical execution and reproducibility, team usefulness, and a clear README and demo. Custom agents and bundled Mattermost are explicitly supported. The completed recorded run covers that workflow using a community-page change.

## Entry links

| Field | Link |
| --- | --- |
| Project | ReleaseRoom |
| Application and video | https://releaseroom-switch.vercel.app/#demo |
| Direct 55-second MP4 | https://releaseroom-switch.vercel.app/demo/releaseroom-demo.mp4 |
| Source and setup | https://github.com/NSEVEjk0/releaseroom-switch |
| Actual release evidence | https://releaseroom-switch.vercel.app/demo/live-release-evidence.json |
| Recorded approved HTML | https://releaseroom-switch.vercel.app/demo/approved-site.html |
| Artifact Git bundle | https://releaseroom-switch.vercel.app/demo/approved-artifact.bundle |
| English captions | https://releaseroom-switch.vercel.app/demo/releaseroom-captions.vtt |
| Recording disclosures | https://releaseroom-switch.vercel.app/demo/recording.json |
| CI | https://github.com/NSEVEjk0/releaseroom-switch/actions/workflows/verify.yml |

## Description draft

ReleaseRoom helps a launch team request, review and release a small webpage change from its team chat. A person asks for new content in Mattermost. Three authenticated Switch roles handle the work: a model-backed builder proposes six inspectable fields, an independent tester checks and pins the artifact, and a release agent asks the person to approve its complete fingerprint.

If the content changes, the earlier approval becomes unusable. Our recorded run shows a genuine human changing the community invitation, seven passing checks, the old approval being rejected, and the current human approval producing a staging page whose HTML hash matches the reviewed artifact. The desk downloads the request, checks and publication receipt.

Switch is the shared transport for the request, agent handoffs and human decision. The controller preserves its authenticated WebSocket state and uses targeted HTTP operations. The builder uses NEAR AI GLM; the tester and publisher are deterministic. The public site includes a 55-second narrated recording, captions, actual release evidence and an interactive release example. Current scope is bounded content staging.

Review this draft in your own voice and be ready to explain the implementation. It is prepared material, not a submitted entry.

## Completed run and verification

- Real self-hosted Switch 0.31.0 and Mattermost room, three connected authenticated agents, actual provider response and genuine human messages on November 7.
- Revision 3 changed the CTA to “Join the community build night” and passed all seven independent checks.
- The actual release agent rejected revision 2's superseded approval, processed the user's original current command, and recorded `human_approved` and `staging_published`.
- Reviewed artifact commit: `c799564b92ad06704a670cf6663d96c68bb19959` in the separate content-artifact repository.
- Approved HTML SHA256: `f7e39ce85cfc20820fd5b9b4f361a6afa70de820dc82bdda29ce5261909393a4`. Staging's body and response header matched it; the live desk's evidence download was exercised.
- Backend checks cover reviewer identities, replay, expiry, supersession, tampering, recovery, current WebSocket/HTTP transport and joined mobile approval arguments. Browser checks cover desktop/mobile review, evidence verification and downloads. The protocol test server and interactive public desk reference remain disclosed fixtures.

## Recording and recovery disclosures

The 55-second recording uses actual browser captures of the real room and controller, with waiting shortened, some motion retimed, and an actual desk screenshot held for the closing scene. Synthetic narration and English captions were added. No human chat request or approval was automated, and no additional generation was run for the film.

Setup exposed a Switch transport/participant identity mismatch, corrected from actual server client records. The first model attempt failed JSON parsing. A subsequent real proposal echoed the context envelope; the operator preserved the model-generated fields and unchanged policy, normalized the wrapper, and sent it through the actual builder/tester/release handoff without another generation. Revision 2 passed. The user's later changed request completed the corrected workflow normally and produced revision 3.

Mobile pasting joined command fields, so the old parser initially ignored the user's approvals. After the parser fix and passing security tests, the operator stopped only the worker service, requeued the earliest original old/current messages unchanged and in arrival order while still recent, recorded that recovery, and restarted the real worker. The release agent performed the rejection, human-approval validation and publication itself. The operator did not call approval or publication directly.

Three model calls were used that day, including the initial failure, within the unchanged eight/day, 1,200-output-token and one-attempt-per-request limits. Public evidence withholds opaque participant identities and raw private room history. It consists of observed controller records and reviewed artifact bytes, not an independent signature or host attestation. The tester and release roles share the controlled host; hashes bind bytes and checks, not the meaning of a request.

## Human entry step

Open the [event page](https://www.wemakedevs.org/hackathons/switch), sign in or register using your own accurate account, select **Best Business Workflow**, and submit the project, repository and video links before **18:29 UTC on November 7**. Review any required form fields yourself and retain the submission confirmation. The chat approval and software publication are complete; the formal hackathon entry has not been submitted.

[Official Rules, section 3](https://www.wemakedevs.org/hackathons/switch/rules) requires a genuine individual to register and submit and prohibits bots or scripts from doing those actions. AI assistance in building is permitted. That is why the final entry action belongs to the human entrant.

## Optional announcement draft

ReleaseRoom turns a team-chat approval into a precise release decision. Request a page change in Switch, inspect the content and checks, and approve the exact revision that reaches staging. A later edit requires a fresh decision. Watch the genuine human/agent workflow and explore the code: https://releaseroom-switch.vercel.app/#demo · https://github.com/NSEVEjk0/releaseroom-switch #HowISwitch

This announcement has not been posted. Social sharing and the blog/Wispr side tracks are optional; the build does not claim Wispr use.
