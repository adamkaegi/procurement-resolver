# Failure Catalogue

Two parts, because they carry different weight:

- **Part A — observed in this warehouse.** Specific defects and hard cases
  found in the real data, with counts and examples. Each was measured, not
  assumed.
- **Part B — known-hard categories.** Resolution failure modes this design
  cannot separate on names alone. Present in the data as a shape, but no
  individual case here is asserted to be a confirmed error — calling one a
  false match would need evidence this project doesn't hold.

Counts are from the current warehouse (23,426 records, 8,916 entities) and
move when it is rebuilt. Nothing here is a precision or recall figure; see
`docs/PROGRESS.md`, "What isn't measured, by decision."

---

## Part A — observed in this warehouse

### A1. Page furniture absorbed into vendor names (fixed)

A table row spanning a PDF page break made the Ottawa parser swallow the
next page's header, footer, and column labels into the vendor field — **97
corrupted names**, worst case 620 characters:
`"DILLON CONSULTING LIMITED CONTRACTS > $25,000 AWARDED UNDER THE DELEGATION
OF AUTHORITY FOR THE PERIOD OF JANUARY 1, 2024 TO JUNE 30, 2024 Page 1 of
28..."`. Root cause: vendor was defined as all text after the amount to the
end of the flattened block, with no page-boundary guard.

Exact-normalized clustering cannot surface this class of defect, because
it never compares one entity against another. Fuzzy blocking does, and it
showed up immediately there — as pairs of unrelated vendors scoring above
the auto-accept threshold on their shared boilerplate. Worth noting as a
general property: a corruption that only manifests in cross-entity
comparison is invisible to exact matching. Fixed by cutting known
furniture off the vendor field: 97 → 0.

### A2. `token_set_ratio` matched any name that was a token subset (fixed)

The scorer compared the shared-token intersection rather than the full
names, so a name whose tokens are a strict subset of a longer one scored
100 regardless of meaning. The toy case is `"Bell"` vs `"Bell Canada"`;
at warehouse scale it was systemic — **3,958 entity pairs auto-accepted**,
including a 30-character firm name matched at 100.0 against a
620-character vendor roster (an A1 casualty).

Switched to `token_sort_ratio`, which compares full sorted strings so
extra tokens cost score: **auto-accepts dropped to 987**, all sampled ones
genuine. `"Bell"` vs `"Bell Canada"` now scores 53.3 and is rejected;
`"Acme Consulting Inc."` vs `"Acme Consulting Group Inc."` abstains at 83.3
instead of matching at 100.0. Regression-pinned by
`tests/test_resolve.py::test_token_superset_is_rejected_not_matched`.

### A3. What fixing A2 cost

Changing the scorer traded one failure profile for a narrower one, and the
new one is real. Against the 30-pair provisional file, `token_sort_ratio`
now **misses** `"CGI Information Systems and Management Consultants Inc."`
vs `"CGI Inc."` (scores 11.3 — a genuine legal-name shortening), because it
penalises the extreme length asymmetry the old scorer ignored by
construction. It still accepts `"Canada Clean Supplies"` vs `"Canada
Cleaning Supplies"` at 93.3: a single-word morphological variant is not
something string similarity can separate from a real variant spelling.

Net on the provisional numbers: federal↔on precision 0.727 → 0.875,
federal↔federal recall 1.0 → 0.667. Precision up, recall on drastic
abbreviations down. Taken deliberately — a false join that fabricates
cross-jurisdiction exposure is worse here than a missed one. Closing the
abbreviation gap needs corroborating evidence (shared buyer, shared
contract identifiers, a registry anchor), not a different string metric.

### A4. Mixed $0 and valued records aggregate without a caveat (open)

Award amounts are frequently absent: **4,427 of 5,000**
`canadabuys_award_notices` records are $0, **1,893 of 5,000** in
`canadabuys_contract_history`, and all **1,822** `ontario_vor` records by
design. The tools caveat a group where *every* record is $0 — but a group
with *some* $0 records reports a count over all of them and a total over
only the valued subset, with no caveat.

In 40 sampled cross-jurisdiction entities, **17 had at least one such
exposure**. Clearest case: `ABI/ADVANCED BUSINESS INTERIORS` reports 23
contracts totalling $18,543 in `canadabuys_award_notices` when **22 of the
23 are $0** — a reader computing an average gets $806 per contract when
the one valued contract is $18,543. Not yet fixed; the fix is to caveat
partial-zero groups the way all-zero groups already are.

### A5. `entity_link` stores one row per occurrence

`entity_link` holds one row per (entity, source, verbatim name)
*occurrence*, not per distinct name — 137 rows for `"Simex Defence Inc."`
in one source alone. `entity_profile` handles this — it selects distinct
links before looking up contracts, returning 333 contracts / 328 distinct
ocids for that entity. But **joining `entity_link` to `releases` directly
without de-duplicating fans out badly**: an un-deduplicated join can
report tens of thousands of contracts for a vendor in a 5,000-row source.
Anyone querying the table directly should expect this.

### A6. Normalization collapses real spelling variance

**1,049 normalized name groups** contain more than one verbatim spelling;
the worst has **18** (`SIMEX DEFENCE` / `SIMEX DEFENCE INC` / `SIMEX
DEFENCE INC.` / …). This is the layer working as intended — suffix,
punctuation, and casing variants of one firm collapsing to one entity
while the verbatim names are preserved in `entity_link` — and it is also
the reason `entity_link` is large (A5).

### A7. Ottawa reports overlap; the same contract appears in several PDFs

Transit reports overlap the broader delegation-of-authority period
reports, so one contract ID can occur in multiple source documents.
**1,019 records** carry a `_provenance.raw_refs` list recording that they
were deduplicated across more than one PDF. Deterministic dedup keeps the
richest record and every raw reference. The two Ottawa *sources* were
deliberately given non-overlapping date ranges, so **0 ocids** appear in
both — the overlap is within `ottawa_contracts_awarded`, not across
sources.

### A8. One contract, many vendors

Some Ottawa delegated-authority rows award a single contract to a roster
of firms, so the vendor field legitimately holds many companies (observed:
60 firms, 620 characters, comma-separated). **26 rows** are flagged
`_provenance.multi_vendor_row` and excluded from entity resolution rather
than split on punctuation — splitting would invent vendors from names that
legitimately contain commas (`"ARCADIS PROF SERVICES (CANADA) INC"`). The
release stays in the warehouse with its verbatim name; it simply asserts
nothing about any single vendor.

### A9. Source semantics that break naive aggregation

- `ontario_vor` publishes **no per-transaction value at all** — every
  amount is a documented zero. It is a registry of standing arrangements,
  not an award ledger. Summing it as spend is wrong by construction.
- `canadabuys_award_notices` and `canadabuys_contract_history` overlap
  `federal_contracts`: the same underlying contract can appear in all
  three without that being a resolution duplicate. No cross-source
  contract-ID reconciliation is attempted within a jurisdiction.
- Federal sources load the **first 5,000 rows in file order** of files with
  ~1.39M / ~786K / ~109K rows — not a random sample, so the loaded slice is
  not representative of the federal population.
- The three levels disclose above **different dollar thresholds**
  ($10K / $25K), so any cross-level total compares differently-censored
  populations. This is what the `coverage` table exists to say out loud.

---

## Part B — known-hard categories

These are shapes the data genuinely contains and that name-only resolution
cannot settle. The counts say how much exposure this warehouse has to each
one; they are **not** counts of confirmed errors.

### B1. Numbered companies

**272 vendor names** begin with a corporation number
(`"2258973 Ontario Inc. (DBA Lucrodyne)"`). Two numbered companies with
the same number in different provinces are different legal entities;
numeric-prefix similarity is not evidence. Blocking indexes the numeric
prefix as its own key so these are compared, but a decision needs
jurisdiction and context.

### B2. Operating name vs legal name

**276 names** carry an explicit operating-name marker (`o/a`, `DBA`) —
`"Affinity Staffing Inc (DBA Affinity Group)"`. The same firm may appear
once as its legal name and once as its operating name with no shared
tokens at all (`"Chantier Davie Canada Inc."` / `"Davie Canada Inc."`
scores 72.7 and correctly abstains). Corroborating context, not string
similarity, is what would resolve these.

### B3. Parent, subsidiary, and holding companies

**29 names** contain "Holdings" (`"Mega Technical Holdings Ltd"`), and
**832** match the `X Canada Inc./Ltd./ULC` pattern
(`"IHS MARKIT CANADA ULC"`). `X Canada Inc.` and `X Holdings Ltd.` may be
the same corporate group and are not the same contracting entity; this
resolver does not model corporate hierarchy, so it must not merge them.

### B4. Divisions of one firm at different levels

A firm may bid federally as one division and municipally as another
(`X Canada` vs `X Public Sector`). They share a parent but are not
necessarily the same contracting entity, and the data carries nothing to
distinguish "division" from "unrelated firm with a similar name."

### B5. Buyer names in the vendor field

**10 vendor names** are recognisably government bodies
(`"MINISTRY OF FINANCE"`, `"UNITED STATES DEPARTMENT OF THE ARMY"`). Some
are legitimate inter-governmental contracting; some are data-entry error.
Buyer context is required to tell them apart, and this resolver does not
use it.

### B6. Altered tokens

Punctuation and casing corruption is removed deterministically (A6), but a
changed token is not corruption — `"Data Services"` vs `"Data Systems"`
scores 64 and is rejected, `"Canada Clean"` vs `"Canada Cleaning"` scores
93.3 and is accepted. String similarity cannot separate a variant spelling
from a different company, so some of these will be wrong in both
directions.

### B7. Commodity and opportunity titles in the vendor field

A commodity description or opportunity title can occupy a vendor field and
look like a company name. The root cause is source semantics, not fuzzy
matching quality; nothing downstream can recover a vendor that was never
published.

### B8. Ontario-incorporated firms have no registry anchor

The optional federal corporations registry only covers federally
incorporated entities, so an Ontario-incorporated firm's absence from it
is not evidence against a match. No registry anchoring is used in this
warehouse; resolution is vendor-to-vendor only.
