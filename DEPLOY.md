# Live Deployment Guide

The brief encourages (does not require) deploying to a live server. The Docker
image is self-contained, so any container host works. Three options, easiest
first.

> Whatever you pick, **change the master password** (`admin_passwd` in
> `config/odoo.conf`) and the Postgres password before exposing it publicly.

---

## Option 1 — Render.com (free tier, no credit card for the basic flow)

Render can run the `docker-compose.yml` via a Blueprint, or run the two
services separately.

**Simplest: a PostgreSQL add-on + a Web Service running Odoo.**

1. Push this repo to GitHub (see below).
2. On Render, **New → PostgreSQL** (free). Note the internal connection host,
   user, password, database.
3. **New → Web Service → Build from a Dockerfile**, pick this repo.
4. Set environment variables on the web service:
   * `HOST` = the Postgres host, `USER`, `PASSWORD` = the Postgres credentials.
   * Render injects `PORT`; Odoo listens on 8069, so add a
     `--http-port=$PORT` to the start command, or set `PORT=8069` and expose
     8069. (Render expects the app on `$PORT` — set the Docker command to
     `odoo --http-port=$PORT --db_host=$HOST --db_user=$USER --db_password=$PASSWORD`.)
5. Deploy. Open the Render URL, create a DB, install the module.

> Free web services sleep when idle and the filesystem is ephemeral — fine for
> a demo, not for real data.

---

## Option 2 — Railway.app

1. **New Project → Deploy from GitHub repo**.
2. Add a **PostgreSQL** plugin; Railway exposes `PGHOST`, `PGUSER`,
   `PGPASSWORD`, `PGDATABASE`.
3. In the Odoo service variables map: `HOST=$PGHOST`, `USER=$PGUSER`,
   `PASSWORD=$PGPASSWORD`.
4. Set the start command to bind Railway's port:
   `odoo --http-port=$PORT`.
5. Deploy and open the generated domain.

---

## Option 3 — Generic VPS (DigitalOcean / Hetzner / EC2 / Lightsail)

The most reliable for a persistent demo.

```bash
# on a fresh Ubuntu 22.04 box
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
git clone <your-repo-url> nn-fund && cd nn-fund
sudo docker compose up -d --build
# Odoo is now on http://<server-ip>:8069
```

For a domain + HTTPS, put Nginx (or Caddy) in front as a reverse proxy to
`localhost:8069`. Minimal Caddy example (`/etc/caddy/Caddyfile`):

```
funds.example.com {
    reverse_proxy localhost:8069
}
```

---

## Pushing the repo to GitHub

```bash
# from the repository root
git remote add origin https://github.com/<you>/nn_fund_management.git
git branch -M main
git push -u origin main
```

Then share the repository link and the live URL in the Google Form.
