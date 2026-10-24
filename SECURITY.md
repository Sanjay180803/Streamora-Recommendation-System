# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: open the repository's
**Security** tab and choose **Report a vulnerability**. Do not open a public
issue for security problems.

Include the affected endpoint or file, steps to reproduce and the impact you
observed. You can expect an acknowledgement within a week.

## Supported versions

Only the default branch (`version2`) of this fork receives fixes.

## Authentication and sessions

- Access tokens are HS256 JWTs signed with `JWT_SECRET` (required, at least 32
  characters; the app will not start without it).
- Tokens expire after `JWT_EXPIRE_MINUTES` (default 60). There are no refresh
  tokens: after expiry the frontend returns to the login page.
- Signing out deletes the token from the browser. Tokens are stateless, so a
  copied token stays valid until it expires; rotating `JWT_SECRET` invalidates
  every outstanding token.
- The frontend stores the token in `localStorage`, so the deployment must be
  served over HTTPS and kept free of untrusted scripts.

## Secrets

- Real credentials belong only in `.env` files, which are gitignored. The
  `.env.example` files contain empty placeholders.
- The TMDB token is used only by the backend proxy. Never give it a `VITE_`
  name: those variables are compiled into public JavaScript.
- CI scans the repository files for secrets with gitleaks.

## Known history

A TMDB read token was committed to this project's history before the
hardening in this fork. The current code does not use it, and it must be
revoked by the account that issued it.
