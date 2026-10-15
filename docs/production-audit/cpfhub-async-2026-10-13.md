# CPFHub asynchronous production rollout — 2026-10-13

Backend `.108`: commit `096e4a35f36f30e623f012fce93ed3572ed6bad3`.
Image `sha256:671e016d818c2addb7a1cb5d4e1d2ae1fb89a597af6c9ef7dc91c74fd865be50`.
Release `/opt/v7m-platform/releases/cpfhub-async-20261013-v108`.
Artifact `3284345253b945de367a2877644b1b82d090954d058c8c0bc5dc0eaea6383570`.
Frontend `.109`: commit `33129f9524f8a65b9f90f63c30a700d70937e8c1`.
Worker version `668a12ce-cf1e-4055-a51f-e261b181ab66`.

## Actual behavior

HTTP funnel calls enqueue CPFHub jobs or read completed results. The provider runs in Django-Q. `users_cpfhublookup` deduplicates CPF requests and persists attempts, lease, result and next attempt. The `users.cpfhub.retry` schedule runs every minute with unlimited repeats and recovers publication failures and interrupted jobs.

Technical errors remain pending and retry indefinitely with exponential delay from one minute to one hour. Provider 404 is a definitive business verdict requiring correction; malformed provider replies retry. Production never substitutes synthetic identities for lookup errors.

Admin notifications use the existing notify-server, stable delivery ids and no CPF, credential or provider body. Unaccepted notifications remain pending for recovery. The frontend polls for up to 30 seconds, then reports that verification continues without completing its profile-completion action. The server job continues independently.

## Evidence

- Complete backend suite: 907 passed.
- Isolated frontend check-types and build passed.
- Frontend Playwright: warmup and two CPF tests passed; pending confirmation did not trigger a second checkout request, completed confirmation did.
- Real production job `15380cfd-98b9-4b17-9c3b-ec9609c4b900` was queued from the web process and completed by the worker: success, attempt 1, real name and birth date present. PII omitted.
- Production schedule: every minute, repeats -1.
- Additive migration `users:0046` applied; origin health passed with zero pending migrations.
- Retry and alert recovery failures were exercised locally. No provider outage was induced in production.

## Rollback

Use the release directory's `compose.rollback.json` to restore the previous web and worker image. Suspend `users.cpfhub.retry` before reverting to code without `users.auth.tasks`. Retain the additive job table and resume pending jobs when the asynchronous release returns. The release changes no runtime settings beyond the explicitly authorized CPFHub credential rotation.

Concurrent app and backend edits were preserved. Artifacts were built from isolated committed source, not unrelated uncommitted edits. No credential is included in this record.
