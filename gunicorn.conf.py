import os

bind = f"0.0.0.0:{os.environ.get('VAULTKEEPER_WEB_PORT', 5985)}"
workers = int(os.environ.get("WEB_CONCURRENCY", 2))
timeout = 30
accesslog = "-"
errorlog = "-"
loglevel = "info"
