# Role pipeline release — 2026-10-11

The latest app/backend publication is CNH renewal release `.91`. The final real UI reupload passed identity matching and original registration/category/expiry comparisons, replacing the previous wrong registration/category and clearing uncertain invalid RENACH. Original full RG JPG also passed on `.91`, after the historical `.89` PNG/PDF and both separate orders with reload. The `.89` extraction failure and two later Scout timeouts are retained as evidence; final success does not establish repeatable provider availability or platform readiness. Only the user homologates delivery.

## Final identity observations and canary cleanup

Original full RG JPG task `fe98f9dc6f8348dfaba01c3805ca6353` completed at `2026-10-12T01:50:08.123Z` with one full source, matching name/CPF/birth date and matching persisted transcription. Final CNH task `765db6dc57d0467bb997c0098dfbece1` ran `01:51:07.532Z`–`01:51:41.389Z`: approved identity, original registration/category/expiry matched both extraction and persistence, stale credentials replaced and uncertain RENACH null. GOWA approvals were observed at `01:50:09Z` and `01:51:43Z`. These UTC times are still 11 October in São Paulo.

The earlier `.91` task `9a0c7fbbd4484e10bee07f37eb6ec40b` reached review at `2026-10-11T21:37:32.299Z` after a 60086 ms Scout read timeout. The final successful reupload used the same timeout/configuration; provider intermittency is still open. Candidate global error text also exposed an old address reason during identity, and checking text remained after review. Address, live selfie, contract and full promoter activation were not exercised.

Temporary candidate/parking-user context was removed; the temporary role revoked, historical suspended promoter restored and original admin/enrollment/staff roles retained. The paid student lead, frozen proposals, existing pending/paid commissions and Diandra's default hub/promoter were preserved. Approved RG/CNH remain stored. The [final sanitized evidence](identity-retest-v91-evidence.json), [full report](identity-retest-2026-10-11.md) and [35 UI case/event records](identity-retest-ui-2026-10-11.json) distinguish real inference, offline tests and controlled rule checks; 35 records are not 35 complete workflows.

Production login was exercised with the owner's authorized account, reading the current OTP through the GOWA MCP. The real role switch reached the hub. `/api/v1/leadership/reviews` returned 500 because `_rg_started_at` was unresolved in `enrollment.coordinator`. The local facade-qualified fix is covered by a regression that executes the actual review query.

Changes include enrollment/candidate OCR serialization and missing helpers, own-document archive for promoters, two calendar months from observed payment confirmation before exam scheduling, required new diploma/history/delivery photo before veteran promotion, failed partner-fee retry and conclusion gates. Only the previous school history is required after enrollment; certificates and other supporting uploads are optional. The identity/selfie approval gate during enrollment remains in place.

Technical checks: 71 focused backend tests passed before the review regression, then 31 student/hub tests passed including that regression. Test boundaries replace external provider/queue calls and are not production OCR or payment evidence. `makemigrations --check --dry-run` reports no missing migration. Additive `users.0043_checkout_paid_at` requires a protected database backup before application. Existing paid proposals retain their pricing.

The exact overlay is listed in `deploy/release/role-pipeline-files.json`. Its base is the live web image, checked by digest. The release controller preserves established runtime credentials, produces an artifact hash/build timestamp, promotes web and qcluster together, and saves their distinct previous images for rollback. It refuses configuration drift and unapplied migrations. It does not deploy the unfinished financial canary module or change commercial prices.

Existing documents and role states must be exercised before claiming complete platform readiness. Numeric exam grades, full hub network finance, payout receipts and broader canary cleanup remain open acceptance work. The historical `.88` RG canary below establishes guarded validation, persistence, live UI and notification for its preserved-file run. A later `.88` upload failed OCR; the subsequent `.89` complete-file PNG/PDF and both separate RG orders with reload passed. Final `.91` RG JPG and CNH identity/credential persistence passed as recorded above. Promoter enrollment end to end and address approval remain pending.

## Published CNH renewal .91

Backend `.91` was built at `2026-10-11T21:31:55.825954Z` and promoted at `2026-10-11T21:35:42.694126Z`, with artifact SHA256 `3466b120c0d98076d5dbe9b3c159326677dc9714a8356ef3140a7a8bfdd69ced`. Web and qcluster use image `sha256:a30a4ae2976b4767fed6fa40958ee796b43c8a9a8f58545209cf86e314319119`; health reported `db=true` and zero pending migrations. App `.91` Worker is `aaab7a43-602a-41da-870f-4175d2310301`, with the app/oracle observation at `2026-10-11T21:36:17.872Z`; app build passed.

The `.90` credential reader preserves Scout identity/validity and returns only Cloudflare Gemma registration/category. The `.91` application path renews stored CNH number/category only after matching identity and valid registration/category. It checks these requirements again before any CNH/profile automatic filling, covering historical extracted payloads used after human approval; the human decision itself is preserved. An uncertain new RENACH clears an invalid old value but retains a valid previous value without a new valid reading. Existing profile data and RG filling behavior are preserved.

The broad local gate passed **137 tests in 10.95 s**. The narrower correction gate passed **80 tests in 5.34 s**, including 20 new renewal cases, across `test_candidate_credential_renewal.py`, `test_candidate_doc_race.py`, `test_identity_visual_transcription.py` and `test_candidate_document_pipeline_contract.py`. These offline adapter/controlled-failure tests are distinct from the earlier 80-test audit and from production model accuracy. The final `.91` real UI reupload renewed previously persisted credentials without clearing them before upload.

### Current rollback reference: .91 to .90

Restore app `.90` Worker `a0033036-e403-491b-8ffe-abab1a275fc8`. From the verified `.91` backend release directory, the reviewed controller command is:

```sh
python release.py rollback --expected-artifact 3466b120c0d98076d5dbe9b3c159326677dc9714a8356ef3140a7a8bfdd69ced
```

The controller restores the saved `.90` web/qcluster images and verifies their digests. This is code rollback only: no database restoration, migration reversal or record changes. No rollback was executed for this documentation update.

## Historical identity recovery .89

App, backend and the Cloudflare gateway `.89` were published together. The backend release is `identity-retest-20261011-v89`, artifact SHA256 `df34b84257ede903705d170eed487e7b63364890d9a556261beca3993a1a4fe7`, image `sha256:fe692adf9baea6537cedcc37573918b0a682fbeb9de34fa0e9041e3bcb7fba86`. It was built at `2026-10-11T20:59:11.085448Z` and promoted at `2026-10-11T21:00:14.346082Z`. App Worker version is `a38a8864-5ec5-498d-a8ab-2487566c5c83`; gateway Worker version is `96bc4518-859e-404f-9eb3-202e3e4bcb56`.

A later real RG upload on `.88` went to review at `2026-10-11T20:54:09Z`, with Cloudflare OCR error “Não foi possível extrair dados estruturados do documento.” The gateway had discarded JSON/thinking options and manufactured `finish_reason=stop` and empty usage, obscuring the upstream response. The successful earlier `.88` canary does not establish repeatable success for later uploads.

The `.89` gateway forwards `response_format`, `chat_template_kwargs` and the pertinent completion/thinking options. Gemma defaults to `enable_thinking=false`; explicit caller options are preserved. Upstream `choices`, `usage` and finish reasons survive intact. A legacy text result without a finish reason returns null and does not manufacture token usage. Authentication, the model allowlist and Cloudflare-only model/provider selection are preserved.

The RG identity reader requests JSON mode and makes at most **two total attempts**, including the initial call. One recovery is allowed for a retryable inference failure or an unstructured response; non-retryable failures stop immediately. Exhausted recovery follows the existing review path. Identity matching, source-generation checks and guarded persistence still decide whether extracted data may be applied.

Student RG polling follows the storage ACK's `poll_after_ms` and absolute `expires_at`, with bounded defaults when metadata is absent. It stops rescheduling at expiry or after settled analysis. Generation and snapshot revision/sequence guards prevent stale GETs from replacing newer receipts. A failed consultation preserves the received files; expiry does not imply approval. Backend TTL/review remains the source of truth.

Local checks passed: 27 focused backend tests, including 4 new bounded-recovery cases; the exact previous 80-test set with offline adapters and controlled failures; 27 frontend tests; Astro checks for 117 files with zero errors; frontend build. Gateway TypeScript, package dry-run and 11 simulated-binding contract cases also passed. The compact previous-test evidence is [identity-retest-local-tests-2026-10-11.json](identity-retest-local-tests-2026-10-11.json). These local checks remain separate from the real `.89` task and UI observations below. Deterministic validator counts and simulated UI contracts cannot be counted as production UI cases.

### Observed production .89 RG capture and duplicate-side rejection

| Authorized real queue task | Started UTC | Completed UTC | Observed result |
| --- | --- | --- | --- |
| Complete RG PNG: `97050aceaa0b4c7a868be242a7180e72` | `2026-10-11T21:01:06.218Z` | `2026-10-11T21:01:17.659Z` | Name/CPF/birth date all `match`; fields filled; only one `full` source |
| Complete RG PDF: `9eb263ca621044658a05cdf0c7345496` | `2026-10-11T21:02:25.552Z` | `2026-10-11T21:02:36.231Z` | Name/CPF/birth date all `match`; fields filled; only one `full` source |
| Separate RG front→back with reload: `400324ed53924cb2b1553bf503522e85` | `2026-10-11T21:07:18.172Z` | `2026-10-11T21:07:24.549Z` | Approved; name/CPF/birth date all `match` |
| Separate RG back→front with reload: `28af36113696488289b20edbe3dc4755` | `2026-10-11T21:08:53.985972Z` | `2026-10-11T21:09:03.718817Z` | Approved; name/CPF/birth date all `match` |

When the UI was requesting the RG back, offering the already received front was rejected with “Esse lado já foi recebido. Envie o verso do RG.” A separate direct backend replay of identical front/back bytes returned `DOCUMENT_SIDE_DUPLICATE` and preserved the original stored front. The later front→back run exercised reload and completed approval. Its screenshot is retained at `app.supletivo.net.br/docs/rg-retest-v89-separated.png`.

Both separate RG orders with reload are now observed as approved. GOWA observed outgoing RG-approved notifications for complete PNG (`3EB0B90F521F5285BE68B6`, `2026-10-11T21:01:18Z`), complete PDF (`3EB06DEB9B841488C164F6`, `2026-10-11T21:02:37Z`) and front→back (`3EB0263968C01C9A9A66BE`, `2026-10-11T21:07:26Z`). No recipient or extracted personal value is reproduced here.

The complete-CNH candidate file was classified as `cnh_full` and no other side was requested. Wrong-name task `02248608881a4040890ea496f12c544a` completed at `2026-10-11T21:13:36.149Z` with rejection and `identity_checks.name=mismatch`, without applying fields. A subsequent matching-identity run exposed the credential failure below. Complete-file PNG/PDF, both separate RG orders with reload and duplicate rejection were the successful `.89` RG outcomes; broader promoter/address and role journeys remain open.

### Observed .89 CNH credential extraction failure

Real queue task `a7602bae46e14bc391ca2c8f9a03594b` ran from `2026-10-11T21:14:06.592Z` to `2026-10-11T21:14:51.304Z`. Name/CPF/birth date matched and the document became approved, but CNH `number` copied `DOC. IDENTIDADE`, including issuing-agency/state letters (`SESP`/UF), and the category was wrong. Comparison with the original PDF confirmed the failure. An approved identity verdict does not establish correct CNH credential extraction; this run cannot be reported as a completed CNH happy path.

The credential reader first published in `.90` retains Scout OCR and its identity JSON, adds a focused Cloudflare Gemma read of registration/category using the original image and four quadrant views, and overrides only those credential fields. Uncertain newly extracted RENACH remains null. The `.91` renewal fix additionally handles existing persisted credentials; corrected queue persistence was observed in the final task above.

The local correction gate passed **43 tests** in `tests/test_identity_visual_transcription.py`, using offline adapters and controlled failures. These cases cover preserving Scout identity/validity, overriding only credentials, missing/invalid number/category, invalid RENACH remaining null and bounded retries. A separate real Cloudflare helper probe matched registration/category to the original PDF; its scope is direct inference, distinct from the final `.91` real queue persistence recorded above.

Real `.90` CNH task `97875c27d5c24d08b76bfb4f44676201` encountered a Scout network timeout after 60,089 ms and reached review at `2026-10-11T21:25:58Z`, without automatic approval or filling. The first `.91` attempt also timed out before the later successful renewal; both failures remain in the audit.

### Production rule checks versus production UI rejection cases

The **19 deterministic cases** came from `.release-build/identity_retest_rules.py` running inside the production container. Fourteen cases mutated name/CPF/birth-date fields from the already stored real OCR in memory; five exercised real file decoding. They invoked validators/decoders without AI inference or database writes. This scope differs from the 80 local offline-adapter tests, real browser interactions and real `.89` queue inference tasks.

The **10 real production UI rejection cases**, run before `.89`, were empty file, unsupported format, oversized file, corrupt JPG, corrupt PDF, encrypted PDF, PDF with three pages, blank PNG, illegible PNG and CNH in the student RG flow. All were rejected; these observations do not establish `.89` happy-path coverage or promoter-CNH acceptance.

The **9 promoter-candidate rejection cases on `.89`** used the genuine chooser: empty file, unsupported format, oversized file, corrupt JPG, blank PNG, illegible PNG, corrupt PDF, encrypted PDF and PDF with three pages. All were rejected. After all nine, `candidate.doc_type` remained null and CNH photo pointers were absent, verified at `21:12 UTC`, before the subsequent complete-CNH capture.

The [sanitized UI export](identity-retest-ui-2026-10-11.json) contains **35 entries**, including the failed attempts and final results. Its event/case count is separate from complete document workflows, approvals, the 19 deterministic production-process rule checks and local offline-adapter tests.

### Historical .89 rollback reference

The app rollback target is `.88` Worker `68c5c611-d875-4ad0-ae97-aa5fde5d664e`; the gateway target is `.88` Worker `a0593d51-3e7f-4204-9357-2483a03734c8`. From the verified `identity-retest-20261011-v89` staging directory, execute the reviewed controller only with the exact `.89` artifact:

```sh
python release.py rollback --expected-artifact df34b84257ede903705d170eed487e7b63364890d9a556261beca3993a1a4fe7
```

The controller restores the saved `.88` web and qcluster images and verifies their digests. It performs code rollback only (`database_rollback=false`): no database restoration, migration reversal or record changes. These are rollback instructions; this documentation update did not execute them.

## Cloudflare-only AI evidence, 2026-10-11

The bounded AI release was deployed separately from the role-pipeline overlay. At the earlier `.84` observation, backend health had `db=true` and zero pending migrations, with artifact `5acb0d3f258cc2d44a7ca5df85203c912e34166c56c4ea3d647f088b4b15631c`. The public Cloudflare Worker gateway `supletivo-ai-gateway.v7m.live` then used version `4581b295-7945-4188-8448-4f5e7f817d52` and accepted only configured Cloudflare Workers AI models.

In the earlier `.82` app / `.84` backend canary, production classified the authorized complete RG as `rg/full` with confidence `0.9`, OCR returned text, structured extraction persisted fields and the enrollment ended `approved` under the older identity rules. That historical status alone did not establish the correctness of the CPF transcription. The same gateway produced a real R2-backed TTS artifact. The async client was corrected to recreate its HTTP client when Django-Q changes event loops; the structured response normalizer was deployed in the gateway. The optional biometric sidecar remained best-effort and was unavailable during that canary.

The observation establishes an exercised storage/inference path. The latest accuracy checks below supersede the earlier RG acceptance claim. The complete student, promoter, hub, partner-fee, payout and notification journeys also remain open acceptance work.

## Published identity capture baseline .87

The app and backend `.87` capture changes are published. This release adds shared RG/CNH capture state, automatic document type on the promoter's first file, storage ACK receipts and missing-face collection without waiting for OCR. Students submit RG only. Both flows recognize `front`, `back` or `full` from the actual file, through one capture area. Unknown recognition cannot invent a slot.

Structured extraction checks the holder name with marriage tolerance, the printed CPF when present and birth date before automatic approval and filling. Filling after a human decision also checks identity before populating fields. Global identity rejection allows recapture even if the individual photo checks passed. Switching between a complete file and separate faces removes the previous mode's pointers and photo verdicts. The successful extraction path rechecks `analysis_started_at` after OCR and discards a completed result from an older upload generation.

JPG, PNG and PDF are supported. PDFium renders the actual PDF composition in an isolated child process, with a two-page limit; it does not replace the source layout with extracted text or selected embedded images.

| Evidence | Observed value |
| --- | --- |
| Backend release | `0.0.0-sandbox.87` |
| Backend artifact SHA256 | `d8bc8ba21cc6ddf3d2c1a680017b0fb2ab5af19393f13828301d1faecd543aca` |
| Backend image fingerprint | `0d9259e…` (reported prefix; not a complete digest) |
| Backend health | `db=true`; zero pending migrations |
| App release / Worker | `0.0.0-sandbox.87` / `cd7d7dc1-fde4-4407-9016-f6e4fcb1036a` |
| Focused tests | 48 backend; 27 frontend passed |

These checks establish technical deployment and covered behavior. They do not establish model accuracy or owner homologation.

## Published identity reader .88

App `.88` is published with Worker version `68c5c611-d875-4ad0-ae97-aa5fde5d664e`. Backend `.88` was built at `2026-10-11T20:17:43.334527Z` and promoted at `2026-10-11T20:19:08.113081Z`, artifact SHA256 `6fc98d4de15c8c8321c29aff15318ebf223629af2a7b3db3ccb30f5f9819d518`, image `sha256:795c8047129d79643a26426da28cc7e72649e607d7f538b7189d476ec3e8cfc5`. Public health returned HTTP 200, version `.88`, `db=true`, zero pending migrations and the expected artifact hash. The release controller verified web and qcluster use the same promoted image. The deployed gateway/oracle `.88` uses Worker `a0593d51-3e7f-4204-9357-2483a03734c8`.

The published reader corrects the missing-CPF contract by normalizing an omitted `cpf_present` to null; an unknown/unreadable presence or invalid CPF goes to review. Generation, status and source paths are checked before applying successful reads, finalizing errors and performing late filling. The profile is reread after inference. PDF classification has a 50-second total budget with up to 45 seconds for inference; both browser flows allow 60 seconds. RG and CNH side descriptions are separate. Address proof still uses the shared classifier and remains outside homologated address acceptance.

Technical checks for this reader: 60 backend and 27 frontend tests passed; Astro checked 117 files with zero errors and the frontend build passed. The deployment evidence above and the production canary below are separate from those tests.

## Observed production RG canary on .88

The same already stored complete RG was preserved, SHA256 `0974c3938952f4780b5896348c51ff7158c335fd8214cc4941515bdec9261aad`, and submitted to an authorized real reanalysis. Queue task `73b93bbbcf084a0e8f43d29b92489b3e` was enqueued at `2026-10-11T20:20:01Z` and completed with `success=true`. The document became `approved` with name/CPF/birth-date identity checks all `match`, validated at `2026-10-11T20:21:23.362152Z`.

Extraction returned `name`, `cpf`, `number`, `ocr_text`, `birth_date`, `birthplace`, `issue_date`, `mother_name`, `father_name` and `issuing_agency`. Persistence checks confirmed the RG number matches the transcription and the birth date matches; parents, birthplace, issuing agency and issue date were filled. No extracted personal values are reproduced here. Production Gemma vision took 13.139 s and OCR/identity reading took 68.355 s.

The real `.88` UI displayed “RG aprovado”, confirmation of both sides in the same file, and “Continuar matrícula”. GOWA observed the outgoing approved-RG notification at `2026-10-11T20:21:25Z`, message ID `3EB02E5E19086DEA831747`. This record contains no phone number or CPF value.

The canary establishes queue execution, guarded identity approval, persistence, live UI and notification for the original preserved RG. It was not a new payment, registration or upload through the UI. Promoter enrollment end to end and address extraction/approval remain pending.

## Real pre-deployment identity readings for .88

Earlier Scout probes misclassified RG verso as `front` and read a wrong CPF from the complete RG. An early Gemma complete-file trial also read the CPF incorrectly. The published RG reader uses one bounded Gemma 4 call with four orientations (0/90/180/270) per source, without sending expected account identity to the model. The corrected complete-RG and RG-back pre-deployment probes both matched name, CPF and birth date; the production reanalysis above subsequently confirmed the complete-RG path.

| Real pre-deployment probe | Observed result | Duration |
| --- | --- | --- |
| Gemma classification, RG front | `front` | 13.03 s |
| Gemma classification, RG back | `back` | 6.95 s |
| Gemma classification, complete RG | `full` | 8.20 s |
| Gemma classification, complete CNH PDF | `full` | 24.80 s |
| Gemma classification, blank image | Not a document | 8.68 s |
| Gemma reading, complete RG, four orientations | Name/CPF/birth date matched | 33.23 s |
| Gemma reading, RG back, four orientations | Name/CPF/birth date matched | 41.55 s |
| CNH reading, Scout OCR plus Cloudflare text JSON | Name/CPF/birth date matched; validity extracted | 25.35 s |

Gemma with duplicated CNH views returned an invalid CPF and therefore review; its single-view trial did not return JSON. The published CNH reader uses Cloudflare Scout OCR and Cloudflare text JSON extraction, without expected name/CPF/birth date in the prompt. RG and CNH share capture, deterministic identity validation and antifraud checks. The earlier real CNH production evaluation matched the identity without mutating registration; the latest pre-deployment reader also extracted validity.

These calls demonstrate the sample readings before deployment. The separate production record above confirms backend `.88` promotion and the approved RG reanalysis with verified persistence. It does not establish a new registration or payment, address approval or the complete promoter journey; those broader journeys remain unhomologated.

All inference remains exclusively on Cloudflare Workers AI through the server-side gateway. Secrets remain in protected runtime configuration or Cloudflare secrets/bindings, never the browser or baked image. Main databases remain Azure; edge data remains D1. The preserved RG has production evidence for its guarded validation path; owner homologation and the remaining promoter/address journeys are separate. See [backend#22](https://github.com/maestri33/backend.supletivo.net.br/issues/22) and [app#17](https://github.com/maestri33/app.supletivo.net.br/issues/17).

## Observed deployment, 2026-10-11 UTC

The `.65` overlay was built as `sha256:2d57b5ac5155f1287d1c494c85d32a58394e24f3468c1bdd648304b647c717c3`, artifact `4635620d6e2691a1276ac0786ba1d358005a2e22690fdb42763812e2361c9eab`. One-process preflight passed in 48.51 seconds. `users.0043_checkout_paid_at` was applied at 06:54:01 UTC after a protected PostgreSQL dump (297601 bytes, SHA256 `5aefee4a3431c55c7e8d8b261538050609bdc23f0d3c7454c6f4a82013f76101`; restore not exercised).

Promotion rolled back both containers after an 8-second subprocess timeout in the old readiness probe. At 07:13 UTC the public backend still identified `.62`; its web image was `fcc2a19c3a83f6449ce1bd3c1c12725fb002b71b9050833692665ae383c277fc`, qcluster `2feccd22d0b9e7b5ff9a854ed0c1a1319a897e9aa785e8f26fb336703acc5e5b`. The additive migration remains applied. These pipeline changes were not live at that observation.

The next recovery removes per-attempt Docker/Python startup from readiness and requires database availability, no pending migrations, exact artifact SHA/version/build time. Forty focused tests passed, including bounded startup retry and rejection of another build. Referral URLs now read the public landing URL from backend configuration; actual UI had exposed `localhost:3000` before this fix.

The Azure VM was observed as `Standard_F1als_v7`, 1 CPU/2 GiB. Linux pressure metrics showed memory full-stall averaging 43.26% over 60 seconds and IO full-stall 54.40%; requests and even Docker inspection intermittently timed out. The user authorized resizing to `Standard_F1ams_v7` (1 CPU/8 GiB). Both PostgreSQL databases were dumped before resizing under `/opt/v7m-platform/backups/pre-memory-resize-20261011/`, and the public IP is static. Record the completed resize and post-restart measurements separately; authorization and invocation alone do not establish completion.

The user changed the canary roles: Diandra coordinates the default hub and becomes the default promoter; Victor must enter as a student through the landing. Their existing financial records and other network members must be preserved. Original identity documents and selfies are required to exercise OCR; documents belonging to Victor cannot establish Diandra's identity.
