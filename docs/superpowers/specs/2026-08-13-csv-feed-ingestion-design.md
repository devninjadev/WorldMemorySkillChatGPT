# CSV Feed Ingestion Design

## Goal

Release World Memory Autopilot v0.9.9 with RSS.app CSV as the only configured FEED format.

## Source boundary

- Replace the five configured `.xml` URLs with the matching `.csv` URLs.
- Do not retain XML parsing or add XML fallback behavior.
- Fetch RSS.app CSV only through the packaged Python direct-HTTP path (`urllib.request`).
- Do not use generic web fetch, web search, or browser navigation as a fallback for the five RSS.app feeds.
- Treat each direct-HTTP or CSV-validation failure as that source's observed error. Preserve independent attempts for all five sources and retain the existing all-five-failed Run policy.

## CSV contract

Require UTF-8 CSV with the exact RSS.app header:

`ID, Feed URL, Feed Link, Feed Title, Feed Description, Feed Icon, Title, Link, Description, Image, Plain Description, Author, Date`

For every row:

- require a nonempty `Date` and parse it as the raw publication timestamp;
- choose identity as nonempty `Link`, else whitespace-collapsed `Title`;
- require a nonempty identity;
- use `Link` as `sourceUrl`, otherwise the configured `.csv` URL;
- retain the existing `-540` minute correction for `first_squawk` and `unusual_whales`;
- fingerprint the exact bytes `feedId + "\n" + identity + "\n" + raw Date`;
- preserve the existing normalized item and durable Feed Batch schemas.

Reject malformed UTF-8, a BOM, missing/extra/reordered headers, empty required values, invalid timestamps, and duplicate CSV columns. Empty but structurally valid feeds remain collection errors in `verify-live`.

## Release

- Update skill and README versions to `0.9.9`.
- Validate the complete unit suite, skill package, live five-feed direct-HTTP path, and release archive.
- Push the release commit directly to `main` as explicitly requested.
- Publish GitHub Release `v0.9.9` with ZIP and SHA-256 assets, then remove the one-time release workflow from `main` after release confirmation.

