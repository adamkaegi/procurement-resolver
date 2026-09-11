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

## Resolved 2026-09-10 — licence confirmed, records loaded

The PDFs were downloaded anyway in a later, unreviewed session (see
`docs/DECISIONS.md`, "Phase 4: Ottawa deterministic extraction") without the
licence question above being answered. That was a gap in the original blocker
handling: extraction proceeded on files whose reuse terms were still
unverified. This entry closes it.

Verified via the City's ArcGIS Hub search API (`ottawa.maps.arcgis.com/sharing/rest/search`)
that the "Contracts awarded / Delegation of Authority" report series is
separately catalogued on the City's actual open data portal (`open.ottawa.ca`),
as public items whose `licenseInfo` points at the City of Ottawa Open Data
Licence v2.0 (`ottawa.ca/.../open-data-licence-version-20`), which permits
copying, redistribution, and reuse with attribution. 7 of the 8 locally
archived PDF filenames matched a catalogued item title exactly; the 8th
matched only by naming-pattern similarity. Full detail and caveats are
recorded in `sources/ottawa_contracts_awarded/source.yaml` under
`licence_verification` — in particular, this confirms the report *series* is
openly licensed, not byte-for-byte identity between the escribe-hosted files
already in `data/raw/` and the open.ottawa.ca catalogue entries.

Decision: load the already-extracted `data/processed/ottawa_contracts_awarded.jsonl`
(2,701 records) into the warehouse. See ADR in `docs/DECISIONS.md`.

Still open for a human: the open.ottawa.ca items are Feature Services
(structured tables), not PDFs. A direct feed from that endpoint would likely
beat PDF text-extraction on both cost and accuracy and should be considered
before any further Ottawa extraction work.