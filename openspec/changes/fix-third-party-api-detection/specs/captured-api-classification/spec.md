## Purpose

Determines whether a captured API request shown in the "review captured requests before saving as a collection" screen is the app's own ("main") traffic or a third-party call, so testers can tell their real backend apart from analytics/maps/CDN/etc. noise and hide the latter.

## ADDED Requirements

### Requirement: Classification reference is the recording script's start URL
The system SHALL classify a captured API request as "main" or "third-party" by comparing its hostname's registrable domain against the registrable domain of the start URL that was recorded for the script that captured it (the URL provided at codegen/record time), not against the domain of any other captured request.

#### Scenario: A third-party call is captured before the app's own API call
- **WHEN** a script recorded against `https://crm.shikho.dev` is run with request capture enabled, and during that run a third-party call (e.g. to `maps.googleapis.com`) completes before the script's own call to `crm-api.shikho.dev`
- **THEN** the request to `crm-api.shikho.dev` is classified "main" and the request to `maps.googleapis.com` is classified "third-party", regardless of which one was captured first

#### Scenario: Subdomain of the recorded site is still "main"
- **WHEN** a script's recorded start URL is `https://crm.shikho.dev` and a captured request's host is `crm-api.shikho.dev`
- **THEN** the request is classified "main", because both hosts share the same registrable domain (`shikho.dev`)

### Requirement: Classification is evaluated per request against its own owning script
When captured requests from multiple scripts are reviewed together (e.g. a suite run), the system SHALL classify each request against the start URL of the specific script that captured it, not against a single start URL shared across all reviewed requests.

#### Scenario: Suite mixes scripts recorded against different sites
- **WHEN** a suite run captures requests from script A (recorded against `https://crm.shikho.dev`) and script B (recorded against `https://partner.otherapp.io`), and the reviewed list contains both scripts' requests together
- **THEN** script A's request to `crm-api.shikho.dev` is classified "main" and script B's request to `partner-api.otherapp.io` is classified "main", each evaluated against its own script's start URL — neither is classified "third-party" because it differs from the other script's site

#### Scenario: A script's own third-party call is still flagged correctly in a mixed review
- **WHEN** the same mixed review as above also contains script B's call to `analytics.google.com`
- **THEN** that request is classified "third-party" (compared against script B's start URL `partner.otherapp.io`), independent of script A's requests being present in the same list

### Requirement: Missing start URL disables classification for that script's requests
If a captured request's owning script has no recorded start URL, the system SHALL treat that request as unclassifiable (not flagged "third-party") rather than comparing it against another script's start URL or against an arbitrary captured request.

#### Scenario: Script has no recorded start URL
- **WHEN** a captured request belongs to a script that has no `start_url_value` on record
- **THEN** that request is not flagged "third-party" and is not counted toward the third-party count, even if other scripts in the same review have a known start URL
