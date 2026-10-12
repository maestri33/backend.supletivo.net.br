# Private biometric service on the existing Azure VM

Owner decision (2026-10-12): evaluate Azure and Cloudflare and choose the option
requiring the least work from the owner. Azure selected: existing 8-GB VM had
6.3 GB available; existing Django integration accepts `/embed`. No new Azure
resource, public port, DNS entry or subscription is required. OCR/vision remains
on Cloudflare Workers AI. Main database stays PostgreSQL on Azure.

Cloudflare alternative: deploy a container image, Worker and Durable Object;
handle model persistence/startup and authenticate backend access. Workers Paid
includes 25 GiB-hours memory and 375 vCPU-minutes monthly; overages apply. This
adds infrastructure and billing compared with the already paid VM.

Sources checked 2026-10-12:
- https://developers.cloudflare.com/containers/platform/pricing/
- https://developers.cloudflare.com/containers/concepts/architecture/

## Runtime and gates

`compose.yml` uses the existing private Docker network and publishes no port.
The process has 2 GiB RAM / 1 CPU limits, restart policy, a persistent model volume
and bounded logs. It keeps no uploaded photos. `/health` only succeeds after the
face model has loaded. Test it from both Django web and qcluster containers.

Build with `docker build -t v7m-biometric:selfie-recovery-v97 .`, start with the
provided compose file, then run `connect_backend.py` on the Azure host as root.
The connector preserves both backend images and all environment variables except
`BIOMETRIC_SERVICE_URL` and `BIOMETRIC_TIMEOUT`; checks model and backend health;
and reverts the backend configuration if a check fails. No migrations.
After connection, run `persist_configuration.py` to persist those two settings
in base Compose. It compares the full resolved configuration before/after and
restores the original on any unrelated change. The original file is retained
with mode 0600 on the VM for rollback.

Do not use a generic vision-language model as a substitute for facial embeddings.
Do not disable the biometric gate or force approval. Reprocess only the owner's
authorized canary through the existing pipeline, preserving its recorded consent.
Its earlier RG embedding may be absent because the same service was unavailable
during document processing; recreate the template from the approved stored RG.

## Rollback and monitoring

`connection-result.json` on the server contains the prior compose-file list and
the unchanged backend image's health identity. Restore those compose files with
`up -d --no-deps --no-build backend-web backend-qcluster`, then stop the biometric
service if necessary. Preserve its model volume. Rollback never fabricates an
approval or undoes audit records.

Monitor container health, restarts, resource limits and biometric `review` errors.
The model is loaded at startup so a health response cannot conceal a cold model.

## Model deployment limitation

This recovers the existing `buffalo_l` model for the authorized owner canary.
InsightFace code is MIT but the project's downloadable model weights have a
noncommercial research policy and separate commercial licensing. No commercial
license evidence was found in this task. General customer rollout requires that
license or an appropriately licensed replacement model with new calibration.
Reference: https://github.com/deepinsight/insightface#license

The existing static-image vision check is not evidence of certified anti-spoofing
or active liveness. The recovery does not claim that capability.

## Observed canary results (2026-10-12)

- VM container healthy, restart count 0, no published ports, approximately
  636 MiB resident memory with a 2-GiB limit.
- Malformed image rejected HTTP 400; image without a face rejected HTTP 422.
- Real stored RG × live selfie comparison returned 0.2434 against the existing
  0.35 approval / 0.28 review thresholds. Thresholds were not changed.
- Recreated the missing approved-document reference, requeued the same stored
  selfie without replacing consent/photo, and observed successful queue completion
  with authoritative `rejected` outcome. Queue emptied. It did not autoapprove.
- GOWA confirmed delivery of the retry notification. Its `{link_app}` remained
  literal because the enrollment notifier only supplied `link`. A regression
  test reproduced this defect; notifier now supplies both names.
- Full backend suite after notifier adjustment: 883 passed in 71.34 seconds.
