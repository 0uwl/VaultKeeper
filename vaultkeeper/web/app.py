"""
VaultKeeper - Flask web application.

Entry point (installed script): web
Manual run from repo root:  flask --app vaultkeeper.web.app:create_app run --host 0.0.0.0 --port 5985
Gunicorn:                   gunicorn "vaultkeeper.web.app:create_app()"  (picks up gunicorn.conf.py automatically)

Environment variables:
  COUCHDB_HOST, COUCHDB_USER, COUCHDB_PASSWORD, COUCHDB_PUBLIC_URL
  FLASK_SECRET_KEY      - set a stable value; sessions reset on restart if unset
  VAULTKEEPER_WEB_PORT  - port for the web server (default: 5985)

"""

import os

from flask import Flask, current_app

from vaultkeeper.client import CouchDB, CouchDBError
from vaultkeeper.logger import get_logger


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

    logger = get_logger(__name__)
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)
    app.logger.propagate = False  # prevent double-logging to root

    from vaultkeeper.web.index import index
    app.register_blueprint(index)
    
    try:
        with app.app_context():
            apply_couchdb_config()
    except CouchDBError as e:
        app.logger.error(f"Warning: server init failed: {e}")

    return app


def run_dev():
    app = create_app()
    port = int(os.environ.get("VAULTKEEPER_WEB_PORT", 5985))
    app.run(host="0.0.0.0", port=port, debug=False)


def apply_couchdb_config():
    couchdb = CouchDB()
    current_app.logger.info(f"Sending server configuration to '{couchdb.host}'")
    couchdb.server_init()


if __name__ == "__main__":
    run_dev()
