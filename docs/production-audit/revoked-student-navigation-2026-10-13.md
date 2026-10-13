# Revoked student environment — corrective release

Authenticated production smoke found a historical paid Lead on the owner test account, no Enrollment/Student record, and revoked lead/enrollment permissions. The canonical resolver inferred student:lead from the historical Lead despite revocation. Client routes then refused access because the active roles no longer included a student journey.

Correction: mirror the existing promoter revocation rule for the student role family. If every student role is revoked, historical entity rows do not restore the student environment. A currently active student-family role still takes precedence, and entity inference remains available for users without revocation history.

No user record, payment, commission, document, matriculation or role is modified. No synthetic student state is created. Complete backend suite: 910 passed. Regression covers whoami with historical paid Lead, revoked role and later explicit re-grant.

Publish only api/health/router.py and users/roles/service.py over the current .110 image. Preflight and promotion use the guarded backend overlay controller. No migration is required. Production verification must confirm the old inaccessible student tab disappears while promoter/admin remain available.
