# Role pipeline release — 2026-10-11

This is a bounded recovery release, not a claim that the platform is ready.

Production login was exercised with the owner's authorized account, reading the current OTP through the GOWA MCP. The real role switch reached the hub. `/api/v1/leadership/reviews` returned 500 because `_rg_started_at` was unresolved in `enrollment.coordinator`. The local facade-qualified fix is covered by a regression that executes the actual review query.

Changes include enrollment/candidate OCR serialization and missing helpers, own-document archive for promoters, two calendar months from observed payment confirmation before exam scheduling, required new diploma/history/delivery photo before veteran promotion, failed partner-fee retry and conclusion gates. Only the previous school history is required after enrollment; certificates and other supporting uploads are optional. The identity/selfie approval gate during enrollment remains in place.

Technical checks: 71 focused backend tests passed before the review regression, then 31 student/hub tests passed including that regression. Test boundaries replace external provider/queue calls and are not production OCR or payment evidence. `makemigrations --check --dry-run` reports no missing migration. Additive `users.0043_checkout_paid_at` requires a protected database backup before application. Existing paid proposals retain their pricing.

The exact overlay is listed in `deploy/release/role-pipeline-files.json`. Its base is the live web image, checked by digest. The release controller preserves established runtime credentials, produces an artifact hash/build timestamp, promotes web and qcluster together, and saves their distinct previous images for rollback. It refuses configuration drift and unapplied migrations. It does not deploy the unfinished financial canary module or change commercial prices.

After promotion, record actual version, commit, artifact/image hashes, migration/backup metadata, public health and real hub UI here. Existing documents and role states must be exercised before claiming completion. Numeric exam grades, full hub network finance, real OCR uploads, canary payments, payout receipts and cleanup remain open acceptance work.

## Observed deployment, 2026-10-11 UTC

The `.65` overlay was built as `sha256:2d57b5ac5155f1287d1c494c85d32a58394e24f3468c1bdd648304b647c717c3`, artifact `4635620d6e2691a1276ac0786ba1d358005a2e22690fdb42763812e2361c9eab`. One-process preflight passed in 48.51 seconds. `users.0043_checkout_paid_at` was applied at 06:54:01 UTC after a protected PostgreSQL dump (297601 bytes, SHA256 `5aefee4a3431c55c7e8d8b261538050609bdc23f0d3c7454c6f4a82013f76101`; restore not exercised).

Promotion rolled back both containers after an 8-second subprocess timeout in the old readiness probe. At 07:13 UTC the public backend still identified `.62`; its web image was `fcc2a19c3a83f6449ce1bd3c1c12725fb002b71b9050833692665ae383c277fc`, qcluster `2feccd22d0b9e7b5ff9a854ed0c1a1319a897e9aa785e8f26fb336703acc5e5b`. The additive migration remains applied. These pipeline changes were not live at that observation.

The next recovery removes per-attempt Docker/Python startup from readiness and requires database availability, no pending migrations, exact artifact SHA/version/build time. Forty focused tests passed, including bounded startup retry and rejection of another build. Referral URLs now read the public landing URL from backend configuration; actual UI had exposed `localhost:3000` before this fix.

The Azure VM was observed as `Standard_F1als_v7`, 1 CPU/2 GiB. Linux pressure metrics showed memory full-stall averaging 43.26% over 60 seconds and IO full-stall 54.40%; requests and even Docker inspection intermittently timed out. The user authorized resizing to `Standard_F1ams_v7` (1 CPU/8 GiB). Both PostgreSQL databases were dumped before resizing under `/opt/v7m-platform/backups/pre-memory-resize-20261011/`, and the public IP is static. Record the completed resize and post-restart measurements separately; authorization and invocation alone do not establish completion.

The user changed the canary roles: Diandra coordinates the default hub and becomes the default promoter; Victor must enter as a student through the landing. Their existing financial records and other network members must be preserved. Original identity documents and selfies are required to exercise OCR; documents belonging to Victor cannot establish Diandra's identity.
