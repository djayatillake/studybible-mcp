# Privacy Policy — Study Bible MCP Server

**Last updated**: 15 October 2026

## Summary

The Study Bible MCP server is a stateless, read-only Bible study tool. It does not collect or transmit personal data. To diagnose errors and slowness it keeps a small, short-lived operational log on its own disk, described below, which never records a full IP address.

## Data Collection

- **No user data is collected or stored.** The server processes each query independently and retains nothing between requests.
- **No cookies, tracking pixels, or analytics** are used.
- **No personally identifiable information (PII)** is requested or recorded.
- **Operational log.** The server keeps a rotating log file on its own disk, capped at about 20 MB, so older lines are overwritten (typically after days to a few weeks). For each request it records the time, endpoint, response status and duration; for each tool call, the tool name, a short excerpt of its arguments (such as a Bible reference, a Strong's number or search words, each cut to 40 characters), the size of the result and the time taken; and, for both, the client software's user-agent and a pseudonymous network tag. The tag keeps only the first three parts of an IPv4 address (the first three groups of IPv6) plus a keyed hash of the full address that changes every day (for example `203.0.113.*~3fa1c2`); the full IP address is never written. The log is used only to find and fix faults, is not shared, and is not used for analytics or user profiling.
- Standard HTTP access logs may also be retained temporarily by the hosting provider (Fly.io) for operational purposes.

## Database Content

The server's SQLite database contains only publicly available biblical texts, lexicons, and scholarly reference materials:

- Bible text (public domain translations)
- Greek and Hebrew lexicons (LSJ, BDB, Abbott-Smith — all public domain)
- STEPBible morphological data (CC BY 4.0)
- BibleAquifer study notes, dictionary, and key terms (CC BY-SA 4.0)
- Theographic genealogy and event data (open source)
- Ancient Near East cultural context entries (compiled from published scholarly sources)

No user-generated content is stored in the database.

## Vector Search (Optional)

If the optional semantic search feature is enabled, search queries may be sent to the OpenAI API to generate vector embeddings. This is a one-time process during database build — the pre-built database already contains embeddings, so **no queries are sent to OpenAI during normal server operation**.

## Third-Party Services

- **Fly.io**: The server is hosted on Fly.io. Their privacy policy applies to infrastructure-level data (IP addresses in access logs, etc.). See [fly.io/legal/privacy-policy](https://fly.io/legal/privacy-policy/).
- **No other third-party services** are contacted during normal operation.

## Authentication

The server requires no authentication. All tools are publicly accessible and read-only.

## Children's Privacy

The server does not knowingly collect any information from anyone, including children under 13.

## Changes

Any changes to this policy will be reflected in this document with an updated date.

## Contact

For questions about this privacy policy, open an issue at [github.com/djayatillake/studybible-mcp/issues](https://github.com/djayatillake/studybible-mcp/issues).
