"""
VaultKeeper - Flask web application.

Entry point (installed script): web
Manual run from repo root:  flask --app vaultkeeper.web.app:create_app run --host 0.0.0.0 --port 5985
Gunicorn:                   gunicorn "vaultkeeper.web.app:create_app()"  (picks up gunicorn.conf.py automatically)

Environment variables:
  COUCHDB_HOST, COUCHDB_USER, COUCHDB_PASSWORD, COUCHDB_PUBLIC_URL
  SECRET_KEY            - required; signs session cookies; generate with: openssl rand -hex 32
  VAULTKEEPER_WEB_PORT  - port for the web server (default: 5985)

"""

import os
import sys

from flask import Flask, current_app

from vaultkeeper.client import CouchDB, CouchDBError
from vaultkeeper.logger import get_logger


def create_app() -> Flask:
    app = Flask(__name__)
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        sys.exit("Error: SECRET_KEY is not set. Generate one with: openssl rand -hex 32")
    app.secret_key = secret_key

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
