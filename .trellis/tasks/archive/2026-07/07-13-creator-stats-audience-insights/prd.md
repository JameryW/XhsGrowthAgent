# Creator stats audience insights

## Goal

Import the complete real Creator Center note snapshot plus aggregate audience insights into the local database, expose the data through analytics APIs, and present useful note-level and audience-level analysis in the web UI.

## Requirements

- Capture native Creator Center responses for note pagination, account traffic sources, viewing periods, and note/account detail metrics through the logged-in browser session.
- Persist normalized public aggregate data locally without storing individual viewer identities or cookies/signatures.
- Keep backward compatibility for existing creator stats rows and fixture/http transports.
- Return audience sources, active viewing periods, and richer note metrics through the analytics response.
- Update the analytics panel to show note coverage, source distribution, active periods, and clear empty/loading states.
- Keep account display name synchronized with the imported Creator Center profile name.
- Add backend and frontend tests for normalization, persistence compatibility, API shape, and UI rendering.

## Risks and guardrails

- Creator Center endpoints are signed and may change. Capture only responses produced by the authenticated browser and degrade gracefully when optional insight endpoints are absent.
- Audience data is aggregate; do not persist viewer-level identifiers or raw authentication material.
- Existing deployments may have rows without the new fields; migrations and defaults must preserve those rows.
