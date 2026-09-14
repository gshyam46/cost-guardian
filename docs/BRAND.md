# Sillage

Selected by the founder on 2026-09-13. Sillage is the wake left by something moving through a medium: a way of understanding what passed through the evidence it leaves. The [Académie française dictionary](https://www.dictionnaire-academie.fr/article/A9S1656) documents that meaning.

For this product, the name connects model calls, timing, usage and failure evidence to a useful question: what happened inside our AI application? The product promise is **understand the evidence your AI leaves behind**. Keep language concrete, calm and precise; do not claim that collecting a trace proves answer quality or fixes an application.

Sillage replaces Cost Guardian in the visible product, sign-in screens, browser metadata and current documentation. Existing `GUARDIAN_*` configuration, `/api/guardian` routes, database identities, module names, repository paths and integration filenames remain compatible. Changing those would require a separate migration with no customer benefit for this visual rename. Helper archives use `sillage-python.zip` and `sillage-node.zip`; their importable modules retain their existing names.

The visual direction is **cream and brick**, refreshed under [ADR-53](DECISIONS.md) and [DESIGN_REFRESH.md](DESIGN_REFRESH.md). Cream paper (`#F6F0E6`), brick actions/selection (`#A64232`), dark brown ink (`#2D2520`) and warm borders (`#DECEC1`) carry through the landing, demo, registration and working application. Navigation uses the same warm paper surfaces; functional states retain clear labels and restrained olive/ochre/error colors. The original S-shaped wake symbol is shared by the wordmark, SVG/ICO favicon and touch icon.

**Instrument Serif** supplies the short display headlines and wordmark; **Manrope** supplies the interface and body. Three Latin WOFF2 files are hosted inside the application, totaling 67,996 bytes. Other scripts use the system fallback. Fonts use `font-display: swap`; no Google Fonts request is needed at runtime. Full redistribution notices ship as `InstrumentSerif-OFL.txt` and `Manrope-OFL.txt`. Sources: [Instrument Serif project](https://github.com/Instrument/instrument-serif), [Manrope font distribution](https://github.com/google/fonts/tree/main/ofl/manrope). Downloaded binaries and checksums are recorded below.

| Font file | SHA256 |
| --- | --- |
| InstrumentSerif-Regular.woff2 | `5eb09b5ac0e28b67c2f041c8ba6d244604ca0c0980d65912ab2d47fed84ddc31` |
| InstrumentSerif-Italic.woff2 | `5a51946dfffa82972bc98745359c46761515641fda557c25116459a9f83da4a7` |
| Manrope-Variable.woff2 | `a30ddcd349703aff7464c34bef3fffdff405ee50c113440d7c8693c02d210972` |

The public sample workspace stays labelled and isolated from live data. Its real selection, measurement and incident interactions explain the product without invented customers or savings. Public actions use Sign up, Sign in and Register. The post-registration waitlist explains availability only after storage acknowledgment; it never claims to create an authenticated workspace account.

This is the selected product name, not trademark or domain clearance. An existing [AI memory package](https://pypi.org/project/sillage/) and [GTM product](https://www.getsillage.com/) also use Sillage. Naming clearance and domain selection remain a business launch decision; no domain was purchased or repository renamed.
