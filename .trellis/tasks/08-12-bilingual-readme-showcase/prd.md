# Bilingual README and Product Showcase

## Goal

Make the repository documentation English-first while preserving a complete Chinese version, and turn the README into a credible product overview grounded in the currently deployed public demo at `https://xhs.jameryw.dev/`.

## Scope

- Rewrite `README.md` as the default English entry point.
- Add `README.zh-CN.md` as the complete Simplified Chinese version.
- Add a language switch at the top of both files.
- Explain the product in terms of user outcomes, workflow stages, workspace surfaces, integrations, and the human approval boundary.
- Add repository-local screenshots captured from the public Showcase and Workflow Replay pages.
- Include the public demo URL and clearly state which surfaces are public and which require login.
- Keep installation, CLI, API, configuration, Ripple CAS, development, testing, and extension documentation discoverable.

## Product claims to preserve

- Public Showcase exposes an approved case and its final content without requiring a login.
- Public Workflow Replay makes the evidence chain inspectable across trend discovery, strategy planning, content creation, and content review.
- The replay result exposes title, body copy, hashtags, key takeaways, image count, and a color palette for the sample case.
- Starting a private creation workflow redirects to login; creation, dashboard, review, analytics, evaluation, history, settings, help, and TUI surfaces are authenticated workspace capabilities.
- The system is a LangGraph multi-agent workflow with a human review gate before publishing.

## Acceptance criteria

1. `README.md` is fully English-first, links to `README.zh-CN.md`, and no longer contains a duplicated Chinese section.
2. `README.zh-CN.md` is a complete Chinese counterpart and links back to `README.md`.
3. Both READMEs describe the live product showcase, workflow stages, outputs, workspace pages, and access boundary accurately.
4. Both READMEs embed the two local screenshots under `docs/assets/readme/` with meaningful alt text and captions.
5. Existing setup and development commands remain present and are not contradicted by the new product description.
6. Markdown links and referenced screenshot files are verified locally; no credentials or private production data are added.

## Out of scope

- Changing frontend behavior, backend behavior, authentication, or deployment.
- Adding a hosted video pipeline or external media upload.
- Claiming that public demo pages can start or publish a workflow without authentication.
