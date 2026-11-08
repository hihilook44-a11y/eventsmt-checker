# Read-only source check

This workflow prints aggregate counts only. It never prints or persists post IDs, text, URLs, media, credentials, or a post ledger; IDs are held in memory only to deduplicate overlapping pages during a single run. The workflow checks at most three pages and counts video posts within a three-hour lookback window (the two-hour schedule overlaps the window to tolerate delayed runs). Pagination duplicates are ignored only within one run; counts may recur between runs, and this does not identify individual new posts or connect to Wabi's private queue.

It does not assess audio, edit video, make thumbnails, or publish. The repository and workflow logs are public. GitHub schedule times are approximate and runs may be delayed or skipped.
