# Deploy the TTBG Help Desk to Render

The included `render.yaml` creates both the Python web service and a private
Render PostgreSQL database.

## 1. Put the project in GitHub

Create a blank private GitHub repository, then run these commands from the
project folder:

```powershell
git init
git add .
git commit -m "Create TTBG internal help desk"
git branch -M main
git remote add origin YOUR_PRIVATE_GITHUB_REPOSITORY_URL
git push -u origin main
```

Before pushing, confirm `.env`, `.venv`, `instance`, and database files are not
listed by `git status`.

## 2. Create the Render Blueprint

1. In Render, select **New > Blueprint**.
2. Connect the private GitHub repository.
3. Render reads `render.yaml` from the repository root.
4. When prompted, enter:
   - `ADMIN_NAME`: the first administrator's display name.
   - `ADMIN_EMAIL`: the first administrator's work email.
   - `ADMIN_PASSWORD`: a new password with at least 12 characters.
   - `NOTIFICATION_EMAIL`: optional inbox that receives new-ticket notices.
5. Create the Blueprint and wait for the deploy to finish.

`SECRET_KEY` and `DATABASE_URL` are configured automatically by the Blueprint.
The database blocks public connections and communicates with the web service
over Render's private network.

## 3. Verify before inviting coworkers

1. Open the Render URL. It should redirect to `/login`.
2. Sign in with the initial administrator account.
3. Submit a test ticket.
4. Change its status, priority, and assignment.
5. Add both a public reply and an internal note.
6. Create a test coworker account from **Team**.
7. Sign in as that coworker and confirm the forced password change.
8. Confirm the coworker can see only tickets submitted by that account.

The machine-only `/healthz` route is intentionally public so Render can check
the app. It returns database status only and exposes no ticket data.

## Optional email notifications

New tickets are stored even when email is disabled or temporarily fails. To
enable email, add these environment variables to the web service:

```text
PORTAL_BASE_URL=https://YOUR-SERVICE.onrender.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=notifications@thetechnicalbridgegroup.com
SMTP_PASSWORD=YOUR_GOOGLE_APP_PASSWORD
SMTP_FROM_EMAIL=notifications@thetechnicalbridgegroup.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
NOTIFICATION_EMAIL=YOUR_SUPPORT_INBOX
```

Use an application-specific Google credential when your Workspace settings
permit it. Do not use a normal Google account password.

## Ongoing administration

- Create and deactivate users from **Team**.
- Use **Reset password** when a coworker loses access.
- Render automatically deploys future commits to `main`.
- Upgrade the free database before relying on the system for long-term
  production records, according to Render's current retention limits.
