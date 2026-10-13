# Lead and partner access contracts — release preparation

Scope: client lead contacts and assigned hub; student partner fee records; staff lead detail and pre-issuance price override. No migration or provider payment is performed by this release.

The client fee response exposes status, amount, scheduled date and paid flags from real PaymentRequest records; internal provider error messages are omitted. Frontends must not infer successful payment from absent records.

Staff GET /leads/{external_id} and PUT /leads/{external_id}/pricing require superuser. Existing checkout or paid lead prevents changing values (LEAD_PRICING_LOCKED). Checkout issuance and price override serialize on the same lead row. No charged proposal or price table is changed by the release.

Checks: complete backend suite 909 passed. New database tests exercise public fee fields, schedule, responsible contacts, editable unissued proposal, and preservation of issued charge. The automated suite is distinct from authenticated production smoke.

Release includes only the five source paths in deploy/release/access-lead-navigation-files.json, overlaid on the current running image. Both web and qcluster must use the same image. Preserve runtime settings, mounted media and networks. Preflight must show zero pending migrations; no migration action is required. The release manifest records image digest, source commit, file hashes and rollback image.
