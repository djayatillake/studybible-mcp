# Privacy Policy — Study Bible MCP Server

**Last updated**: 17 March 2026

## Summary

The Study Bible MCP server is a stateless, read-only Bible study tool. It does not collect, store, or transmit any personal data.

## Data Collection

- **No user data is collected or stored.** The server processes each query independently and retains nothing between requests.
- **No cookies, tracking pixels, or analytics** are used.
- **No personally identifiable information (PII)** is requested or recorded.
- Standard HTTP access logs may be retained temporarily by the hosting provider (Fly.io) for operational purposes, but these are not used for analytics or user profiling.

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
