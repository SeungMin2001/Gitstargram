# Security Policy

## Reporting a Vulnerability

Do not open public GitHub issues for security vulnerabilities or secret leaks.

Please report suspected vulnerabilities privately to the repository owner with:
- Affected endpoint or component (`apps/api`, `apps/web`, `scripts/embedding_server.py`)
- Reproduction steps and impact assessment

## Core Security Controls Implemented

- **GitHub App User OAuth with PKCE (`S256`) and `state` validation**: Prevents authorization code interception and CSRF during login (`/api/auth/login`, `/api/auth/callback`).
- **Encrypted GitHub Tokens at Rest**: GitHub user access and refresh tokens are encrypted with `Fernet` (`cryptography`) before storage in `github_accounts`. Browser clients never receive GitHub tokens.
- **Opaque HttpOnly Session Cookies**: Browser sessions use random tokens stored only as SHA-256 hashes (`auth_sessions.token_hash`).
- **Same-Origin Verification**: State-mutating `POST`/`PUT`/`PATCH`/`DELETE` endpoints enforce `Origin` header validation via `require_same_origin`.
- **Untrusted README Prompt Isolation**: README summarization and translation treat repository markdown strictly as untrusted data.
