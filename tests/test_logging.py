"""Tests for vaultkeeper.logger - log file placement and message content."""

import logging

import pytest

from vaultkeeper.logger import _create_default_logging_config, get_logger


@pytest.fixture
def log_setup(tmp_path, monkeypatch):
    """Configure logging to a temp directory and yield (logger, log_file_path)."""
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    config = _create_default_logging_config()
    logger = get_logger("test.vaultkeeper", logging_config=config)
    yield logger, tmp_path / "vaultkeeper.log"
    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)


def test_log_file_placed_in_log_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    config = _create_default_logging_config()
    assert config["handlers"]["file"]["filename"] == str(tmp_path / "vaultkeeper.log")


def test_default_log_dir_is_var_log(monkeypatch):
    monkeypatch.delenv("LOG_DIR", raising=False)
    config = _create_default_logging_config()
    assert config["handlers"]["file"]["filename"] == "/var/log/vaultkeeper.log"


def test_log_file_created_on_first_write(log_setup):
    logger, log_file = log_setup
    logger.info("file creation check")
    assert log_file.exists()


def test_info_message_written_to_file(log_setup):
    logger, log_file = log_setup
    logger.info("hello from test")
    content = log_file.read_text()
    assert "[INFO]" in content
    assert "hello from test" in content


def test_error_message_written_to_file(log_setup):
    logger, log_file = log_setup
    logger.error("something went wrong")
    content = log_file.read_text()
    assert "[ERROR]" in content
    assert "something went wrong" in content


def test_log_format_includes_logger_name(log_setup):
    logger, log_file = log_setup
    logger.info("format check")
    content = log_file.read_text()
    assert "test.vaultkeeper" in content


def test_multiple_messages_all_written(log_setup):
    logger, log_file = log_setup
    logger.info("first message")
    logger.error("second message")
    content = log_file.read_text()
    assert "first message" in content
    assert "second message" in content
