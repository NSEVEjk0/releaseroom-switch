# ReleaseRoom entry preparation

## Problem, solution and useful distinction

A chat approval can outlive the content it approved. ReleaseRoom makes a launch-page request move through a model-backed builder, an independent tester and a release agent in Switch. A human reviews the actual fields and checks, then approves the exact request, revision, commit and artifact fingerprint. Changed content needs a new decision.

The useful distinction is the complete handoff: the same room carries the work and approval, and staging serves the checked bytes. The current product is bounded page-content staging. It does not deploy arbitrary generated code or guarantee that a model understood the request.

## Readiness and required evidence

- Public [reference desk](https://releaseroom-switch.vercel.app) and [repository](https://github.com/NSEVEjk0/releaseroom-switch).
- Backend, identity, stale-approval, tamper and recovery checks; current authenticated protocol integration; browser review flow.
- Actual Switch/Mattermost room and three agent profiles are prepared on the operator VPS. Service readiness, genuine model-generated work and actual human approval must be confirmed before claiming the live workflow complete.
- The demo must show at least one actual person and agent completing real work through Switch. A scripted reference is supporting evidence only.
- Human registration and submission by **7 November 2026, 18:29 UTC**.

The [official brief](https://www.wemakedevs.org/hackathons/switch) assesses central use of Switch, reproducibility, team usefulness and presentation. Its presentation criterion explicitly calls for a demo video and README. [Official rules](https://www.wemakedevs.org/hackathons/switch/rules) reserve registration and submission to genuine human entrants.

## Required recording: 55 seconds maximum

Record the actual completed workflow. Prepare the two proposals in advance; shorten idle waiting in editing without presenting it as instantaneous work. Never hide the reference-example label or send an approval as the reviewer through automation.

| Time | Show | Explain |
| --- | --- | --- |
| 0–7 s | Team request in the real Switch/Mattermost conversation | A team can approve one page version and accidentally ship another. |
| 7–18 s | Builder proposal, tester handoff and live desk | ReleaseRoom turns the request into six inspectable fields and independent checks. |
| 18–29 s | A changed request and the actual old-approval rejection | A later edit invalidates the previous approval. |
| 29–43 s | Human sends the new full-fingerprint approval; verified staging opens | The person decides in Switch. The release agent publishes the checked artifact. |
| 43–55 s | Evidence download and repository | Current scope is content staging; exact fingerprints bind bytes, not the meaning of the request. |

Keep the total below 60 seconds. Retain the original room evidence privately. Share only the demonstration content the human agrees to make public, and keep credentials off-screen.

## Announcement draft

ReleaseRoom gives a team’s “approved” a precise meaning. Ask for a page change in Switch, inspect the content and independent checks, then approve the exact revision that reaches staging. A later edit requires a fresh review. The public desk shows a disclosed engine reference; the connected team workflow uses a real human reviewer. Explore the desk and code: https://releaseroom-switch.vercel.app · https://github.com/NSEVEjk0/releaseroom-switch

Rewrite the announcement in your own voice and update the live-workflow statement only after its genuine demonstration passes. This draft has not been posted.

## Submission outline

Use your own words for the actual entry: the team’s approval problem, why Switch is essential, the real request/handoff/approval evidence, the bounded artifact and revision binding, reproduction steps, what remains limited, and the required recording URL. Disclose the scaffold, model provider and fictional reference example.
