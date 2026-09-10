# Blocked: Ottawa document extraction

## Phase 4

The Ottawa Delegation of Authority extraction acceptance test could not be run.

- The official City of Ottawa search and council pages returned an Incapsula anti-bot challenge instead of page content. The response was HTTP 200 but contained `Request unsuccessful` and no report links.
- The reachable meeting publication host, `pub-ottawa.escribemeetings.com`, is a third-party surface. Its page did not expose an open-data licence, and the licence could not be verified from the available response.
- No Ottawa PDF or HTML report was downloaded, archived, transformed, or sent to an extraction model.
- Consequently, no validating Ottawa records or per-document extraction-cost log were produced.

This is a source-verification and licensing blocker, not a reason to substitute a
different Ottawa source. Phase 5 proceeds with the federal and Ontario records
only, as permitted by the run instructions.