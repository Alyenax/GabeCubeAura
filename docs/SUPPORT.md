# Optional project support

Official destination: **https://ko-fi.com/alyenax**.

GabeCubeAura remains free and open source, including future public releases and
public betas. Donations do not unlock features, priority updates or beta access.

The README has one separate support button near the download links and one
short section after the feature demonstrations. `.github/FUNDING.yml` already
contains `ko_fi: alyenax`; it does not need a duplicate entry. The reusable
[release-note block](RELEASE_NOTES_SUPPORT.md) is for future notes only.

## Measurement is optional

Current links go directly to Ko-fi without campaign parameters. No tracking
script, redirect service, donation widget or click reporting has been added.

Ko-fi documents a Google Analytics 4 integration that requires Contributor
status: [Ko-fi analytics documentation](https://help.ko-fi.com/hc/en-us/articles/360007169993--Connect-your-Ko-fi-page-to-Google-Analytics).
The owner's account configuration has not been inspected. Do not assume that
Ko-fi supplies a native per-link click counter or that analytics is enabled.

If the owner chooses a measurement system later, this convention can identify
the five entry points. Every value is fixed; never include user, device or game
identifiers in a support URL.

| Entry point | Proposed `utm_source` | Proposed `utm_medium` |
| --- | --- | --- |
| README | `github_readme` | `project` |
| Decky About & Support | `decky_about` | `plugin` |
| Decky Updates | `decky_updates` | `plugin` |
| Demonstration site | `concept_site` | `website` |
| Release notes | `github_release` | `project` |

Use `utm_campaign=gabecubeaura_support` consistently. Google documents how
[campaign parameters are collected](https://support.google.com/analytics/answer/11242841).
Parameters alone do not count clicks. Before adopting this convention, verify
that Ko-fi preserves them and that the intended analytics reports actually
show each source. Page visits, outbound clicks and completed donations are
different measurements; do not claim donation attribution from traffic alone.

Do not activate analytics or add an external reporting service without a
separate decision by the owner. Measurement is not required for these support
links to work.
