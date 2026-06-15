# Development

## Repository structure

```
.
├── vaultkeeper/                    # Python package
│   ├── __init__.py
│   ├── client.py                   # Core CouchDB module - shared by CLI and web app
│   ├── cli.py                      # Click-based CLI (entry point: cli)
│   └── web/
│       ├── __init__.py
│       ├── app.py                  # Flask app factory (create_app) + main() entry point
│       ├── index.py                # Blueprint "index"
│       ├── templates/              # Jinja2 HTML templates (Bootstrap 5)
│       └── static/                 # CSS overrides
├── tests/
│   ├── conftest.py
│   ├── test_server.py
│   ├── test_users.py
│   ├── test_vaults.py
│   └── test_setup_uri.py
├── docs/                           # Extended documentation
├── Dockerfile
├── pyproject.toml                  # Package definition, dependencies, scripts
└── README.md
```

## Building the container

```bash
docker build -t vaultkeeper .
```

## Python dependencies

Defined in `pyproject.toml`. To install for local development:

```bash
pip install -e .             # installs cli and web scripts
pip install -e ".[dev]"      # also installs pytest and testcontainers
pip install -e ".[serve]"    # also installs gunicorn
```

Core dependencies: `click`, `requests`, `flask`

## Running with Gunicorn

```bash
pip install -e ".[serve]"
cli server init
export FLASK_SECRET_KEY=$(openssl rand -hex 32)
gunicorn "vaultkeeper.web.app:create_app()"
```

`gunicorn.conf.py` in the project root is picked up automatically. It binds to
`$VAULTKEEPER_WEB_PORT` (default 5985) and defaults to 2 workers; override with
`$WEB_CONCURRENCY`. Access and error logs go to stdout/stderr.

In the container, `docker-entrypoint.sh` runs `cli server init` then starts Gunicorn
automatically - no manual init step is needed.

## Testing

Tests run against a real CouchDB instance - no mocking. A
[testcontainers](https://testcontainers.com/) fixture starts a `couchdb:3.5.1` Docker
container automatically.

```bash
pytest                                          # starts a test container
COUCHDB_TEST_URL=http://localhost:5984 pytest   # use an existing instance
```

Tests in `test_setup_uri.py` require Deno and `generate_setupuri.ts` and are automatically
skipped when Deno is not on PATH (i.e. outside the container).
