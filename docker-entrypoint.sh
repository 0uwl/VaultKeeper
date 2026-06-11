#!/bin/sh
set -e
cli server init
exec gunicorn "vaultkeeper.web.app:create_app()"
