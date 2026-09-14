# Sillage: cream and brick design refresh

## Revision requested by the founder, 2026-09-15

The founder further asked for an interesting, lively and immersive feel. Keep the working investigation, but lighten heavy dark panels into cream/peach surfaces and add a clickable visual call flow. Curved wake paths and a replay-driven progress marker connect the actual sample calls; motion starts only through user interaction. Apply the same warmer surfaces to sign-in and registration. This is functional movement and selection feedback, with reduced-motion support.

The first pass overused large serif headlines with a brick italic second phrase. The founder rejected that repeated pattern. Keep cream and brick, but replace the display/body pairing with one upright Hanken Grotesk family throughout the product; use IBM Plex Mono only for compact measurements and sequence labels. Headlines stay a single ink color. Hierarchy should come from size, weight, spacing, rules and composition rather than italic emphasis. The wake symbol remains the identity anchor, with a quieter upright wordmark.

Make the sample investigation the main public experience: a working inspection surface with selectable runs/calls, user-triggered replay and pause, a keyboard-operable timeline scrubber, measurement lenses and an adjustable demo duration rule. These interactions operate only on labelled illustrative data. Scrubbing reveals recorded sample calls; it must not invent live traffic or imply raw-content/full-RAG capture. A rule comparison is a local simulation, not a saved production policy, incident mutation or projected savings claim. Keep unknown costs unknown and retain the existing incident/resolution interaction.

Use an asymmetric, compact landing composition and a practical source-to-investigation explanation. No auto-playing demo, scroll interception, ornamental particle backgrounds or repeated feature-card grids. Respect reduced motion, tab order, touch targets and 320px layouts. Sign up, Sign in and committed-save waitlist behavior remain unchanged. Implement the landing composition and demo in parallel, then verify actual interactions and refresh both local previews. This revision supersedes the typography and headline treatment described in the original delivery below.

### Revised delivery

The revised experience is implemented: upright typography, lighter peach/cream surfaces, interactive curved call flow, user-controlled replay/scrubbing, measurement lenses, sample rule comparison and the source explorer. Pending flow nodes cannot reveal uncaptured measurements. Selecting a flow node pauses replay and opens the same evidence as the timeline. Reduced motion hides the travelling marker and removes hover transforms; native keyboard controls remain available.

The final builds and all 410 frontend tests pass. Both local previews are refreshed; registration records remain in their separate local database and existing workspace data is preserved. [VALIDATION.md](VALIDATION.md) records current browser, native and artifact evidence. The original delivery below is retained as history.

Recorded before implementation on 2026-09-14, following the founder's request for a premium, less formulaic product identity across the public site and workspace.

## Direction

Use cream paper (`#F6F0E6`), brick (`#A64232`), deep brown ink (`#2D2520`) and warm borders (`#DECEC1`). Brick is the primary action and selection color. Keep functional success/warning/error states distinguishable with labels as well as color. Replace the green navigation and generic stacked-layer symbol. Draw a small original vector wake mark and use the same silhouette in the wordmark, favicon and app metadata.

Typography combines locally hosted Instrument Serif for short display headlines and the wordmark with Manrope for navigation, forms, tables and body copy. Keep numerical data readable with tabular figures. Include the fonts' redistribution licenses. No third-party font request should be needed to render the product.

The landing page should lead with a clear product promise and one substantial interactive investigation. Use deliberate spacing, editorial composition and concise examples of the questions Sillage helps answer. Avoid stock feature-card grids, decorative gradients, oversized ornamental metrics, invented customer logos, fabricated savings and unsupported live-data claims. Keep sample data explicitly labelled. Interactions should help a visitor understand the workflow or evidence, work with keyboard/touch, and respect reduced motion.

Apply the palette to the whole Sillage frontend: landing/demo, registration/sign-in, sidebar/navigation, overview/live/run details, charts, tables, connections, policies, notifications, empty/error states and focus rings. Retain existing permissions, data semantics and responsive behavior. Founder Path is a separate customer application and is outside this Sillage visual scope.

## Registration journey

Public navigation and primary calls to action use **Sign up**, **Sign in** or **Register**. The form is a straightforward registration surface rather than an early-access pitch. Keep contact consent and the privacy notice visible and accurate. Do not introduce passwords or claim a verified account, workspace or authenticated session exists.

After the independent registration API confirms committed storage, clear entered details and show the dedicated `/waitlist` confirmation explaining workspace availability and the next step. A direct visit or reload of `/waitlist` must not claim that an unconfirmed registration was saved. Failed, timed-out or malformed responses stay on the form with an actionable message and retained inputs. Existing workspace sign-in remains with the configured OIDC backend; readiness never proves authentication or provisioning. The data schema, consent, duplicate protection, retention and operator workflow remain as defined in [PUBLIC_LAUNCH.md](PUBLIC_LAUNCH.md).

## Delivery and evidence

1. Record the identity, registration and runtime boundaries before code.
2. Implement the landing/demo, workspace theme and registration journey in parallel with disjoint ownership; integrate matching local fonts and vector assets.
3. Verify interactions, confirmed-save navigation, direct waitlist entry, error recovery and existing auth boundaries. Build both public and ordinary workspace modes from explicit source inputs.
4. Inspect desktop/mobile browser screenshots, font loading, branding consistency and key real workspace routes. Refresh the owned preview while preserving its data and backend processes; provide a public-mode preview when needed to make signup reviewable.
5. Update current brand, architecture, progress and validation docs with actual results and remaining hosted-deployment setup. Do not claim deployed Vercel or account provisioning from a visual refresh.

## Delivered, 2026-09-15

All five delivery steps are complete locally. The public experience now leads with an interactive call investigation and a concise workflow/evidence explanation. Cream/brick styling covers workspace navigation, data views, connection and monitoring controls, forms and state messages. Both builds ship the same locally hosted fonts, wake mark, favicon, touch icon and manifest colors. Registration uses the ordinary Sign up / Sign in / Register language and the confirmed-save waitlist contract above.

The full frontend suite, focused server/build and static-boundary checks, 69 workspace browser scenarios, ten public browser/Mongo phases and all eight native deployment phases pass. Native acceptance includes real local OIDC, worker processing, incident resolution, restart persistence and database transport recovery. Public pages also passed font loading and overflow checks at 320, 390 and 1280 pixels with no external requests. [VALIDATION.md](VALIDATION.md) records counts, artifacts and the browser cleanup diagnostic repair.

The refreshed local public preview is `http://127.0.0.1:3004`; the existing workspace is `http://127.0.0.1:8001/welcome`. Existing workspace data and runtime dependencies were retained. Public preview registration uses a separate local database and synthetic privacy contact. Hosted Vercel/database/contact setup and self-service workspace provisioning remain separate work.
