import logging
import logging.config
import os


DEFAULT_FORMAT = (
    '[%(asctime)s] '
    '[%(levelname)s] '
    '%(name)s:%(lineno)d - '
    '%(message)s'
)
GUNICORN_FORMAT = (
    '[%(asctime)s] '
    '[%(process)d] '
    '[%(levelname)s] '
    '%(name)s:%(lineno)d - '
    '%(message)s'
)
MAX_BYTES = 10 * 1024 * 1024     # 10 MB
BACKUP_COUNT = 3

def _create_default_logging_config(level = logging.INFO):
    log_dir = os.getenv("LOG_DIR", '/var/log/')
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, 'vaultkeeper.log')

    config = {
        'version': 1,
        'disable_existing_loggers': False,

        'formatters': {
            'default': {
                'format': DEFAULT_FORMAT
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
                'stream': 'ext://sys.stdout'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'default',
                'filename': log_file,
                'maxBytes': MAX_BYTES,
                'backupCount': BACKUP_COUNT
            }
        },

        'root': {
            'level': level,
            'handlers': ['console', 'file']
        }
    }

    return config

def get_logger(name: str, logging_config=None):
    """Returns the appropriate logger. If gunicorn is used, return the gunicorn.error logger. Otherwise, return a custom logger. 
        If no logging_config is passed, the default logger is returned which includes a stream handler and a rotating file handler

    Args:
        log_dir (str): The directory where log files are placed
        logging_config (dict, optional): The configuration dict for the custom logger. Defaults to None.

    Returns:
        logging.Logger: The logger that the app should use
    """
    gunicorn_logger = logging.getLogger('gunicorn.error')
    if gunicorn_logger.handlers:
        for handler in gunicorn_logger.handlers:
            handler.setFormatter(logging.Formatter(GUNICORN_FORMAT))
        return gunicorn_logger
    
    config = logging_config or _create_default_logging_config()
    try:
        logging.config.dictConfig(config)
    except ValueError:
        # File handler couldn't be configured (e.g. log directory not writable); fall back to console only.
        level = config.get('root', {}).get('level', logging.INFO)
        console_only = {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {'default': {'format': DEFAULT_FORMAT}},
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'default',
                    'stream': 'ext://sys.stdout',
                }
            },
            'root': {'level': level, 'handlers': ['console']},
        }
        logging.config.dictConfig(console_only)

    new_logger = logging.getLogger(name)
    return new_logger