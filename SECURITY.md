# Security Policy

## Supported status

This repository is a research prototype and is not approved for production clinical use.

## Reporting

Do not open a public issue containing secrets, patient information, credentials, database files, or exploit details. Contact the repository owner privately through the security reporting channel configured on GitHub.

## Sensitive data

Never commit `.env`, `private/`, SQLite databases, credential exports, authentication peppers, session tokens, real patient records, or unredacted clinical conversations. Rotate a secret immediately if it is exposed.

## Implemented controls

- Server-side opaque sessions use `HttpOnly`, `SameSite=Lax` cookies; production startup requires `Secure`.
- Authenticated writes require CSRF, and browser requests are restricted to same-origin or explicit origins.
- Host headers are allowlisted; production startup disables public OpenAPI/Swagger pages.
- Request bodies have a hard byte limit before JSON parsing.
- Login traffic is limited by HMAC-fingerprinted IP and account buckets; assistant traffic is limited per user.
- RBAC is enforced at the API boundary, while services and repositories enforce ownership and care/coordination scope.
- Ordinary request logs contain no request body and pass through sensitive-data redaction.
- Security audits store request IDs and HMAC fingerprints and are append-only through SQLite triggers.
- The response policy blocks framing, MIME sniffing, unnecessary browser permissions, and inline scripts.

The development SQLite limiter and in-process application remain single-instance prototype controls. A production Linux deployment must use HTTPS, external secret management, a shared rate-limit store, centralized append-only audit storage, and an approved clinical security review.

Development pages currently load Tailwind's browser CDN. Production CSP blocks that domain; production assets must be compiled and self-hosted before deployment.
