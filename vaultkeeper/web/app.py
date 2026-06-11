"""
VaultKeeper - Flask web application.

Entry point (installed script): vaultkeeper-web
Manual run from repo root:  flask --app vaultkeeper.web.app:create_app run --host 0.0.0.0 --port 5985
Gunicorn:                   gunicorn "vaultkeeper.web.app:create_app()"

Environment variables:
  COUCHDB_HOST, COUCHDB_USER, COUCHDB_PASSWORD, COUCHDB_PUBLIC_URL
  FLASK_SECRET_KEY      - set a stable value; sessions reset on restart if unset
  VAULTKEEPER_WEB_PORT  - port for the web server (default: 5985)

Note: when running under Gunicorn, main() is not called, so server init does not
run automatically. Run `cli server init` before starting Gunicorn, or rely on the
compose.yml healthcheck ordering which already handles this.
"""

import os
import sys

from flask import Flask

from vaultkeeper.client import CouchDB, CouchDBError


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

    from vaultkeeper.web.routes import bp
    app.register_blueprint(bp)

    return app


def main():
    app = create_app()
    port = int(os.environ.get("VAULTKEEPER_WEB_PORT", 5985))
    try:
        CouchDB().server_init()
    except CouchDBError as e:
        print(f"Warning: server init failed: {e}", file=sys.stderr)
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
