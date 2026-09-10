# Resolution Failure Catalogue

These are deliberately preserved cases for resolution review. They describe
failure modes and root causes, not measured production metrics.

1. Numbered companies with identical legal names can be the same entity only when jurisdiction and context agree; name-only matching cannot distinguish them.
2. Numbered companies with different provincial suffixes are distinct legal names; numeric-prefix similarity is not sufficient evidence.
3. An operating name such as `Davie Canada` may omit the legal prefix `Chantier`; the relationship needs corroborating context.
4. A legal suffix omission such as `IBM Canada Limited` versus `IBM Canada Ltd.` is a normalization case, not a new entity.
5. A parent such as `Davie Holdings Ltd.` must not be merged with `Chantier Davie Canada Inc.`; the root cause is corporate hierarchy, which this resolver does not model.
6. A subsidiary such as `Microsoft Canada Inc.` must not be merged with `Microsoft Corporation`; the root cause is parent/subsidiary ambiguity.
7. Divisions recorded as `X Canada` and `X Public Sector` can share a parent but are not necessarily the same contracting entity.
8. Punctuation and casing corruption can be removed deterministically, but an altered token such as `Data Services` versus `Data Systems` requires abstention or adjudication.
9. A commodity or opportunity title can look like a vendor name; the root cause is source semantics, not fuzzy matching quality.
10. A government buyer name can appear in a vendor field after data-entry error; buyer context is required to avoid a false match.
11. Ontario-incorporated firms absent from the federal registry cannot be rejected merely because no registry candidate exists.
12. Empty, footer, and note rows are not vendors; source-row filtering must happen before normalization.
