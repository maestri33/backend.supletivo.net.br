# Isolated production payment canary — 2026-10-11

This change permits the authorized owners to exercise the real landing and payment funnel without changing the commercial price or commission settings. It does not confirm that the entire platform works or replace the owner's acceptance.

The protected run requires an active staff actor, a justification, exactly two CPF/phone identities, an allowlisted recipient and a maximum 72-hour lifetime. At most five new proposals receive signed, immutable terms: Pix BRL 1.01, card BRL 1.02 in one installment, direct commission BRL 0.01, one weekly bonus BRL 0.10 at five paid sources, and coordinator commission BRL 0.05. Expiration stops new proposals; existing proposals retain their issued amounts.

Each credit must resolve a confirmed checkout belonging to the signed proposal and intended recipient. Canary sales and refund debts have a separate run identifier and never enter the commercial weekly bonus or payout batch. Before bank submission, the worker checks the signed terms, source purchase, recipient, CPF Pix, exact batch sum and BRL 0.40 maximum. Canary commission accrual and confirmed payout use identified double-entry transactions. These identifiers support reconciliation; they are not proof of provider settlement.

Technical checks: 65 local tests passed, including rejection before bank I/O, source tampering, expiration, refund carryover, candidate holds, commercial-rate preservation and release probing. `makemigrations finance --check --dry-run` detected no model changes. These tests use local fixtures and do not constitute production receipts.

Deployment uses a pinned overlay on the current backend image, an explicit `finance:0009` migration after a database backup, separate build/preflight/promotion steps, web/queue image identity and an origin health check. Rollback restores the previous code image; the additive migration remains. A backup restore has not been exercised.

Production acceptance still requires actual landing capture, provider settlement/webhook reconciliation, the generated commission, notifications, documents and live camera capture. Friday closing and the two-calendar-month exam gate must retain their real time boundaries. Do not change payment timestamps or activation dates to present a simulated transition as real evidence.
