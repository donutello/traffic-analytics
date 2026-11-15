# Deploy

Two ways to run the dashboard: a **demo run** on one machine (the exact production shape, only on localhost) and **production on a VPS** (the same steps plus HTTPS). Both need one server only: FastAPI answers under `/api` and serves the built frontend from `frontend/dist` under `/` ([ADR 0002](adr/0002-frontend-react-vite.md)).

The customer's raw data (`analysis/data/raw/`, not committed) is needed by nobody on the server: the database is built from the results committed in `analysis/output/` ([ADR 0010](adr/0010-server-database-from-import.md)).

You need [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/) 24 on the machine.

## Demo run (one machine, any OS)

```sh
uv sync                                      # Python packages
rm -f traffic.db                             # optional: start from an empty database
uv run python -m backend.load                # load every committed road into traffic.db
cd frontend && npm ci && npm run build       # frontend/dist
uv run uvicorn backend.main:app --port 8000  # one process: API + dashboard
```

Open <http://localhost:8000>: the dashboard, backed by `/api` on the same address. The database file `traffic.db` and the port are the repository defaults (`DATABASE_PATH` and `--port` move them if you like). FastAPI serves `frontend/dist` only when it exists, so without the build you get the bare API, exactly as during development.

The same as one line, bash:

```sh
uv sync && uv run python -m backend.load && (cd frontend && npm ci && npm run build) && uv run uvicorn backend.main:app --port 8000
```

and Windows PowerShell:

```powershell
uv sync; uv run python -m backend.load; cd frontend; npm ci; npm run build; cd ..; uv run uvicorn backend.main:app --port 8000
```

The import replaces each road's rows, so running it again (or the whole demo a second time) is harmless.

## Preview on the temporary container (leasewi.com:50549)

While there is no VPS yet, the dashboard is shown to the customer through a throwaway preview container ("summit", same host as the dev box). It has no network access from its app units (no DNS, no PyPI, no npm), so nothing can be installed there: the app is shipped as a self-contained directory from the dev box and runs with the container's own Python. The `site` tool does the transfer: `push` copies a directory to `~/www/<port>` and `take` runs a command there as a systemd unit. Three steps from the repository root after each merge to `main` you want visible:

```sh
# 1. build the frontend locally
(cd frontend && npm run build)
# 2. assemble a self-contained app dir: backend code, results, dist, and the Python packages
#    as a plain --target directory (same Python 3.13 linux x86_64 on both sides)
D=$(mktemp -d)/app && mkdir -p $D/frontend $D/analysis
cp -r backend contract $D/ && cp -r frontend/dist $D/frontend/ && cp -r analysis/output $D/analysis/
cp pyproject.toml uv.lock $D/
uv export --no-dev --no-hashes --frozen -o $D/requirements.txt
uv pip install -q -r $D/requirements.txt --target $D/site-packages --python 3.13 --no-cache
# 3. ship it and (re)take the port; load runs on every start and is idempotent
site push 50549 $D
site take 50549 -- sh -c 'export PYTHONPATH=site-packages; P=$(readlink -f $(command -v python3)); $P -m backend.load && exec $P -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"'
```

Always do BOTH commands. `push` is an rsync with delete and wipes `traffic.db` (the database `take` builds at startup), and it does not restart the running unit: after a push alone the app keeps answering from its response cache, while anything uncached hits an empty database and fails with 500 «no such table». `take` reruns the import and replaces the unit in place, so <http://leasewi.com:50549> answers seconds later (HTTP only, no auth — anyone with the address sees it). `site ssh journalctl --user -u web-50549 -n 30` shows the app log if it does not. The database is built on the container from `analysis/output/` on every start, exactly like the demo run; raw data never travels.

## Production on a VPS

On the server, the demo steps once, then keep two things running: the app as a service, and a small proxy in front with HTTPS.

```sh
git clone https://github.com/donutello/traffic-analytics /srv/traffic-analytics
cd /srv/traffic-analytics && uv sync --locked
uv run python -m backend.load
(cd frontend && npm ci && npm run build)
```

### The app as a systemd service

`/etc/systemd/system/traffic-analytics.service` (adjust the user and paths; `uv` must be installed for that user):

```ini
[Unit]
Description=Traffic Analytics dashboard
After=network.target

[Service]
User=traffic
WorkingDirectory=/srv/traffic-analytics
Environment=DATABASE_PATH=/srv/traffic-analytics/traffic.db
ExecStart=/home/traffic/.local/bin/uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

then `sudo systemctl daemon-reload && sudo systemctl enable --now traffic-analytics`.

### HTTPS in front: Caddy

Caddy is the two-line option: it requests and renews the certificate itself and redirects HTTP to HTTPS automatically ([NFR5](requirements.md)). `/etc/caddy/Caddyfile`:

```
analytics.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Point the domain at the server, `sudo systemctl reload caddy`, done. Put the app on `127.0.0.1` only so nothing bypasses the proxy.

nginx works the same with `certbot --nginx` for the certificate:

```nginx
server {
    listen 80;
    server_name analytics.example.com;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl http2;
    server_name analytics.example.com;
    # ssl_certificate and ssl_certificate_key: certbot --nginx manages them
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Updating the data and the code

Every deploy is the same few commands, and the import makes it idempotent — re-running just refreshes the database:

```sh
git pull && uv sync --locked
uv run python -m backend.load
(cd frontend && npm ci && npm run build)
sudo systemctl restart traffic-analytics   # also clears the in-process response cache
```

### Secrets

There are none today: the database is a local file built by the import ([ADR 0010](adr/0010-server-database-from-import.md)). If we switch to a Turso Cloud database or an embedded replica later, `TURSO_AUTH_TOKEN` (and the database URL) go into `Environment=` in the unit file or an environment file outside the repository — never into git, the repo is public.

### Deploying from main

The rule is: deploy `main` only when CI is green. Today CI (GitHub Actions, `.github/workflows/ci.yml`) runs on every push to `main` but deploys nothing: a person pulls and runs the commands above by hand, after the checks pass. Once a server exists, this can become an automation; until then the gate is a human looking at the green tick.

### To decide on the server day

The domain name, the server itself (a small VPS is enough), the SSH user, and whether to keep Caddy or use nginx; the certificate email if nginx + certbot is chosen.
