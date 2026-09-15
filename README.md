# TTBG Internal Help Desk

A private ticketing system for The Technical Bridge Group. Every human-facing
page requires an account; there is no public registration.

## Included workflows

- Coworkers submit access requests, software issues, security concerns,
  development tasks, or other requests.
- Coworkers see only tickets they submitted and can add follow-up replies.
- Administrators see the complete queue, search and filter tickets, assign
  work, change status/priority, and add private notes.
- Administrators create, deactivate, reactivate, and reset team accounts.
- New users must replace their temporary password at first sign-in.
- Optional email notification when a new ticket is submitted.
- PostgreSQL support and a one-click Render Blueprint.

## Local setup (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set a unique administrator email and password. The password
must have at least 12 characters.

```powershell
python run.py
```

Open <http://127.0.0.1:5000>. Sign in with the `ADMIN_EMAIL` and
`ADMIN_PASSWORD` values from `.env`.

## How to use it

1. Sign in as the administrator.
2. Open **Team** and create an account for each coworker.
3. Give each coworker their temporary password securely.
4. The coworker signs in and is forced to create a new password.
5. Coworkers submit and track requests from **New ticket**.
6. Administrators manage the full queue from **Tickets**.

## Roles

| Capability | Coworker | Administrator |
| --- | --- | --- |
| Submit a ticket | Yes | Yes |
| View own tickets | Yes | Yes |
| Reply on own tickets | Yes | Yes |
| View every ticket | No | Yes |
| Assign/update tickets | No | Yes |
| Add requester-hidden notes | No | Yes |
| Manage team accounts | No | Yes |

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Production deployment

See `DEPLOYMENT.md`. Keep `.env` private and never commit passwords or database
credentials. Local SQLite is for development only; the Render Blueprint uses
PostgreSQL so tickets persist across deploys.
