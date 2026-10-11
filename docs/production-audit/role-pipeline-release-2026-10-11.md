# Role pipeline release — 2026-10-11

This is a bounded recovery release, not a claim that the platform is ready.

Production login was exercised with the owner's authorized account, reading the current OTP through the GOWA MCP. The real role switch reached the hub. `/api/v1/leadership/reviews` returned 500 because `_rg_started_at` was unresolved in `enrollment.coordinator`. The local facade-qualified fix is covered by a regression that executes the actual review query.

Changes include enrollment/candidate OCR serialization and missing helpers, own-document archive for promoters, two calendar months from observed payment confirmation before exam scheduling, required new diploma/history/delivery photo before veteran promotion, failed partner-fee retry and conclusion gates. Only the previous school history is required after enrollment; certificates and other supporting uploads are optional. The identity/selfie approval gate during enrollment remains in place.

Technical checks: 71 focused backend tests passed before the review regression, then 31 student/hub tests passed including that regression. Test boundaries replace external provider/queue calls and are not production OCR or payment evidence. `makemigrations --check --dry-run` reports no missing migration. Additive `users.0043_checkout_paid_at` requires a protected database backup before application. Existing paid proposals retain their pricing.

The exact overlay is listed in `deploy/release/role-pipeline-files.json`. Its base is the live web image, checked by digest. The release controller preserves established runtime credentials, produces an artifact hash/build timestamp, promotes web and qcluster together, and saves their distinct previous images for rollback. It refuses configuration drift and unapplied migrations. It does not deploy the unfinished financial canary module or change commercial prices.

After promotion, record actual version, commit, artifact/image hashes, migration/backup metadata, public health and real hub UI here. Existing documents and role states must be exercised before claiming completion. Numeric exam grades, full hub network finance, real OCR uploads, canary payments, payout receipts and cleanup remain open acceptance work.
