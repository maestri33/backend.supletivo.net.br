# Preparing access and contact ownership

Platform .99 added backend-derived release stages, responsible coordinator and
the student tracking screen with animated SVG, document/payment sections and
an adaptive four-item dock. Full backend suite: 899 tests passed.

Owner correction in the same delivery: when the paid lead becomes an enrollment,
the promoter's mission ends. Enrollment inherits the promoter's hub; that hub's
manager becomes responsible. The WhatsApp button must use this manager's profile
phone. A separate official contact field is not required.

Patch .100 therefore derives `release.contact_url` from
`Enrollment.hub.coordinator.profile.phone`, normalized to an E.164 wa.me link.
It does not use the promoter phone or the student's phone. Missing/invalid numbers
produce no guessed link. Tests cover manager and promoter being distinct people.
Schema already supports nullable URLs; existing production frontend renders the
WhatsApp button when this value is returned.

No migrations or finance actions. Rollback restores the prior backend image while
preserving the biometric service configuration. Canary screenshot and release
identities are kept in local outputs/.release-build.
