import logging
import logging.config
import os

from datetime import datetime

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

def _create_default_logging_config(log_dir: str, level = logging.INFO):
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    log_file = os.path.join(log_dir, f'vaultkeeper_{timestamp}.log')

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

def get_logger(name: str, log_dir: str = './', logging_config=None):
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
    
    config = logging_config or _create_default_logging_config(log_dir)
    logging.config.dictConfig(config)

    new_logger = logging.getLogger(name)
    return new_logger