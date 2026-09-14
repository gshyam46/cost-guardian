# Sillage

Selected by the founder on 2026-09-13. Sillage is the wake left by something moving through a medium: a way of understanding what passed through the evidence it leaves. The [Académie française dictionary](https://www.dictionnaire-academie.fr/article/A9S1656) documents that meaning.

For this product, the name connects model calls, timing, usage and failure evidence to a useful question: what happened inside our AI application? The product promise is **understand the evidence your AI leaves behind**. Keep language concrete, calm and precise; do not claim that collecting a trace proves answer quality or fixes an application.

Sillage replaces Cost Guardian in the visible product, sign-in screens, browser metadata and current documentation. Existing `GUARDIAN_*` configuration, `/api/guardian` routes, database identities, module names, repository paths and integration filenames remain compatible. Changing those would require a separate migration with no customer benefit for this visual rename. Helper archives use `sillage-python.zip` and `sillage-node.zip`; their importable modules retain their existing names.

The visual direction is **cream and brick**, revised under [ADR-54](DECISIONS.md) and [DESIGN_REFRESH.md](DESIGN_REFRESH.md). Cream paper (`#F6F0E6`), brick actions/selection (`#A64232`), dark brown ink (`#2D2520`) and warm borders (`#DECEC1`) carry through the landing, demo, registration and working application. Use upright, single-color headlines; hierarchy comes from composition, spacing and weight. The founder rejected the earlier repeated serif/brick-italic treatment. Navigation uses warm paper surfaces; functional states retain clear labels and restrained olive/ochre/error colors. The original S-shaped wake symbol is shared by the upright wordmark, SVG/ICO favicon and touch icon.

**Hanken Grotesk** supplies headlines, wordmark, interface and body in one upright family. **IBM Plex Mono** is reserved for compact numeric measurements, code and sequence labels. Two Latin WOFF2 files are hosted inside the application, totaling 49,412 bytes. Other scripts use the system fallback. Fonts use `font-display: swap`; no Google Fonts request is needed at runtime. Full redistribution notices ship as `HankenGrotesk-OFL.txt` and `IBMPlexMono-OFL.txt`, with only trailing whitespace normalized. Sources: [Hanken Grotesk distribution](https://github.com/google/fonts/tree/main/ofl/hankengrotesk), [IBM Plex project](https://github.com/IBM/plex). Downloaded binaries and checksums are recorded below.

| Font file | SHA256 |
| --- | --- |
| HankenGrotesk-Variable.woff2 | `e9201eddf1d41d0b62253295d869ce3cf65768f7102b797f02c7f8c876b4a9d5` |
| IBMPlexMono-Regular.woff2 | `08949f728dc52d528e69b1667d15c89a5686a4ee9a296ff90983985f99c380f7` |

The public sample workspace stays labelled and isolated from live data. User-controlled replay, timeline scrubbing, duration/token/cost lenses and a simulated duration rule explain how to investigate calls. The simulation never saves a customer policy, changes the recorded sample incident or claims a production saving. Public actions use Sign up, Sign in and Register. The post-registration waitlist explains availability only after storage acknowledgment; it never claims to create an authenticated workspace account.

This is the selected product name, not trademark or domain clearance. An existing [AI memory package](https://pypi.org/project/sillage/) and [GTM product](https://www.getsillage.com/) also use Sillage. Naming clearance and domain selection remain a business launch decision; no domain was purchased or repository renamed.
