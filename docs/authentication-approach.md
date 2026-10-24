# Authentication

YouHoard has one local account. On a fresh database, the web UI prompts for a username and password. `POST /api/auth/setup` creates that account atomically and rejects further setup requests. Passwords require at least eight characters and are stored as bcrypt hashes.

`POST /api/auth/login` returns a bearer token and sets an HttpOnly, SameSite=Lax session cookie. The cookie uses Secure when the request is HTTPS. Sessions are stored in SQLite and expire after `SESSION_EXPIRE_MINUTES` (30 days by default). Existing sessions with legacy UTC timestamps remain valid until expiry.

Protected routes validate the cookie or an `Authorization: Bearer <token>` header. Media and thumbnails use the same authentication; the storage directory is not publicly mounted. Missing/expired sessions return HTTP 401. Logout invalidates the session and removes the cookie.

Cookie-authenticated mutations reject a mismatched Origin header. Vite proxies preserve the browser's host during development. A production reverse proxy must forward the correct host and scheme.

This is a private LAN/tailnet application, not a public service. Complete initial setup on a trusted network. HTTPS, login throttling and deployment hardening need to be addressed before exposing it outside that boundary.
