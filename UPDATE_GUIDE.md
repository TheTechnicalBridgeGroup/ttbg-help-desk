# TTBG Help Desk — branding and secure password recovery

## Deploy this update to your EXISTING service

1. Back up the existing production database before deploying. Keep the existing Render service and database.
2. Replace the application files in your existing GitHub repository with this ZIP's project contents. Do not upload your local `.env`, virtual environment, `instance/`, or database files.
3. Keep the current `DATABASE_URL`, administrator settings, SMTP credentials and strong `SECRET_KEY` in Render. This update does not replace existing users, passwords or tickets. If the current secret is a placeholder or shorter than 32 characters, replace it with a strong random secret before deployment; production startup now rejects weak/default secrets. Never put secrets in GitHub.
4. Set `PORTAL_BASE_URL` to the exact public HTTPS origin of this help desk, for example `https://ttbg-help-desk.onrender.com` (or your actual help desk custom domain). No path, query or fragment. Reset URLs never trust a visitor's Host header.
5. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL`. Recovery messages require `SMTP_USE_TLS=true` (usually port 587) OR `SMTP_USE_SSL=true` (usually port 465), according to your mail provider. Use a dedicated/app credential supported by your provider, not someone's normal sign-in password. `NOTIFICATION_EMAIL` is not needed for password resets: each link goes only to the email stored on that user's account.
6. Deploy. Startup's existing `db.create_all()` adds `password_reset_tokens` and `auth_rate_limits`; it does not alter/drop existing tables. Ensure the database deployment credentials can create these tables. If schema changes require approval in your database environment, apply the new table definitions there first. No new paid service or queue is required.
7. Everyone will sign in again once after this update because sessions now include a password-bound identifier. Thereafter password changes/resets invalidate prior sessions on every device. Normal in-account password changes refresh only that current session.
8. Complete the live acceptance checks below before announcing recovery availability.

## Live acceptance checks (required; local tests do not prove email delivery)

- Check `/healthz`, sign in, open an existing ticket and confirm its contents.
- Sign out, choose **Forgot your password?**, and request a reset for your own active account.
- Confirm delivery, sender, HTTPS help desk domain and the 15-minute expiry wording. Check spam. Do not forward the link or paste it into logs.
- Open the emailed link in a browser with JavaScript enabled; choose and confirm a new password. Confirm the old password fails and the new one works. Confirm a previously signed-in browser is sent back to login.
- Reopen the same email link and try again: it must fail. A link older than 15 minutes must also fail.
- Unknown and disabled-account email addresses should receive no reset mail. All valid email submissions should display the same generic message.
- Check desktop/mobile ticket pages and team administration.

## Recovery protections

- Available on the login page; only administrator-created, active accounts qualify. No account registration is added. Email syntax is validated; the emailed token proves mailbox access. Arbitrary people cannot change a password simply by entering an email address.
- 256-bit random tokens, SHA-256 token hashes stored in the database, 15-minute lifetime, atomic single use. No passwords appear in emails. Successful reset invalidates every outstanding link for that account.
- Multiple requested links can remain valid until a reset succeeds or they expire. Requesting another link does not cancel the previous one or change/lock the account.
- Shared database rate limits apply across web workers: reset requests allow 20/IP/hour, 3/email/hour and 1/email/minute; reset submissions allow 20/IP/15 minutes. Limits use fixed windows and count requests, including unknown emails. Repeated clicks count toward the hourly limit; after reaching it, wait for the next hourly window. Limits never deactivate accounts.
- Login attempt limits: 30/IP/15 minutes and 10/email/15 minutes, counting successful and unsuccessful attempts. These are temporary request limits, not account deactivation.
- Generic responses and bounded asynchronous email processing avoid exposing account existence through SMTP delays. Rate-limit keys use HMACs instead of raw emails or IPs.
- CSRF checks, HTTPS-only recovery URLs, encrypted SMTP, no-cache/no-referrer headers. Reset tokens travel in URL fragments, which browsers do not send to servers in HTTP requests, and JavaScript clears the fragment after moving it into the form. Do not configure infrastructure/APM to log POST bodies or email contents.
- Passwords remain hashed by Werkzeug; new/reset passwords must be 12–128 characters. Password confirmation is required. Resetting does not automatically sign the user in.
- A password-changed alert is sent after self-service, in-account and administrator password changes. Alert delivery failure does not undo a password change.
- Administrator temporary-password recovery remains available for independently verified users who cannot access their mailbox. Resetting no longer silently reactivates a disabled account; activation is a separate administrator action.

## Operational notes

- Verify existing account email addresses with team members before enabling recovery; mail goes to the address already stored on the account. Protect work mailboxes with MFA. Email-only recovery is only as secure as those mailboxes; centralized company sign-in with enforced MFA is the stronger future option.
- The existing Render one-proxy-hop configuration is retained. If you add another proxy, review trusted forwarding configuration and rate-limit client IP attribution before deployment.
- A bounded in-process email queue avoids an extra service but is not durable: a crash/redeploy may discard queued emails. Request another link after the cooldown. Under queue saturation or email configuration/delivery failure, users still see the same generic message; operators receive a credential-free error in application logs. A durable job queue can be added if scale requires it.
- Expired rate-limit buckets/tokens are pruned during normal use. You can also run `flask --app run.py cleanup-auth` periodically to remove expired authentication records.
- Never disable CSRF in production. `WTF_CSRF_ENABLED=False` is used only in local automated tests.

## Validation completed

All 35 tests in the original ticket/notification suite and new security regression suite pass locally. Browser checks cover desktop/mobile layouts, recovery navigation, normal sign-in, and fragment-token handling. Actual Render/PlanetScale deployment and real mailbox delivery require the acceptance checks above; no live changes or real recovery emails were made during development.

Security reference: https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html
