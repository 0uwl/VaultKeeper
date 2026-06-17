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
from werkzeug.middleware.proxy_fix import ProxyFix

from vaultkeeper.client import CouchDB, CouchDBError
from vaultkeeper.logger import get_logger


def create_app() -> Flask:
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        sys.exit("Error: SECRET_KEY is not set. Generate one with: openssl rand -hex 32")
    app.secret_key = secret_key

    logger = get_logger(__name__)
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)
    app.logger.propagate = False  # prevent double-logging to root

    from vaultkeeper.web.main import main
    from vaultkeeper.web.auth import auth
    from vaultkeeper.web.users import users
    from vaultkeeper.web.vaults import vaults
    from vaultkeeper.web.audit import audit
    from vaultkeeper.web.backup import backup
    app.register_blueprint(main)
    app.register_blueprint(auth)
    app.register_blueprint(users)
    app.register_blueprint(vaults)
    app.register_blueprint(audit)
    app.register_blueprint(backup)
    
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
