#!/usr/bin/env python3
"""Tests for Tesla solar download project."""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from freezegun import freeze_time

from config import DownloadStats
from structured_logger import (
    JSONFormatter,
    setup_logging,
    log_operation,
    retry_with_logging,
)


# Fixtures


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def temp_log_file(temp_dir):
    """Create a temporary log file path."""
    return os.path.join(temp_dir, 'test.jsonl')


@pytest.fixture
def clean_logging():
    """Clean up logging handlers before and after each test."""
    # Clean before test
    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.setLevel(logging.WARNING)

    yield

    # Clean after test
    root_logger.handlers = []
    root_logger.setLevel(logging.WARNING)


# Tests for DownloadStats


class TestDownloadStats:
    """Tests for the DownloadStats class."""

    def test_initial_values(self):
        """Test that DownloadStats initializes with zeros."""
        stats = DownloadStats()
        assert stats.files_downloaded == 0
        assert stats.files_skipped == 0
        assert stats.files_failed == 0
        assert stats.total_records == 0
        assert stats.api_calls == 0
        assert stats.total_duration_ms == 0
        assert stats.errors == []

    def test_to_dict_no_downloads(self):
        """Test to_dict with no downloads (success_rate should be 0)."""
        stats = DownloadStats()
        result = stats.to_dict()
        assert result['files_downloaded'] == 0
        assert result['success_rate'] == 0

    def test_to_dict_with_success(self):
        """Test to_dict with successful downloads."""
        stats = DownloadStats()
        stats.files_downloaded = 10
        stats.files_failed = 2
        stats.total_records = 1000
        stats.api_calls = 15

        result = stats.to_dict()
        assert result['files_downloaded'] == 10
        assert result['files_failed'] == 2
        assert result['success_rate'] == 10 / 12  # 10 / (10 + 2)
        assert result['errors'] == 0

    def test_to_dict_with_errors(self):
        """Test to_dict counts errors list length."""
        stats = DownloadStats()
        stats.errors = ['error1', 'error2', 'error3']
        result = stats.to_dict()
        assert result['errors'] == 3


# Tests for Structured Logging


class TestJSONFormatter:
    """Tests for the JSON log formatter."""

    def test_formats_basic_message(self, clean_logging):
        """Test that JSONFormatter outputs valid JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg='Test message',
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed['level'] == 'INFO'
        assert parsed['message'] == 'Test message'
        assert 'timestamp' in parsed

    def test_includes_extra_fields(self, clean_logging):
        """Test that extra fields are included in JSON output."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg='Test message',
            args=(),
            exc_info=None,
        )
        record.operation = 'test_op'
        record.site_id = '12345'
        record.duration_ms = 123.45

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed['operation'] == 'test_op'
        assert parsed['site_id'] == '12345'
        assert parsed['duration_ms'] == 123.45


class TestLoggingSetup:
    """Tests for logging setup."""

    def test_setup_logging_console_only(self, clean_logging):
        """Test logging setup without file output."""
        setup_logging(log_file=None)

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) == 1
        assert isinstance(root_logger.handlers[0], logging.StreamHandler)

    def test_setup_logging_with_file(self, clean_logging, temp_log_file):
        """Test logging setup with file output."""
        setup_logging(log_file=temp_log_file)

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) == 2  # Console + file

        # Verify log file was created
        assert os.path.exists(temp_log_file)

    def test_setup_logging_creates_directory(self, clean_logging, temp_dir):
        """Test that setup_logging creates log directory if needed."""
        log_file = os.path.join(temp_dir, 'logs', 'nested', 'test.jsonl')
        setup_logging(log_file=log_file)

        assert os.path.exists(log_file)
        assert os.path.isdir(os.path.dirname(log_file))

    def test_logging_outputs_json_lines(self, clean_logging, temp_log_file):
        """Test that file output is valid JSON lines."""
        setup_logging(log_file=temp_log_file)
        logger = logging.getLogger(__name__)

        logger.info('Test message 1', extra={'operation': 'test1'})
        logger.info('Test message 2', extra={'operation': 'test2'})

        # Read and parse JSON lines
        with open(temp_log_file) as f:
            lines = f.readlines()

        # Skip the first line (logging init message)
        assert len(lines) >= 2

        # Parse each line as JSON
        for line in lines[1:]:
            parsed = json.loads(line)
            assert 'timestamp' in parsed
            assert 'level' in parsed
            assert 'message' in parsed


class TestLogOperation:
    """Tests for the log_operation context manager."""

    def test_log_operation_success(self, clean_logging, temp_log_file):
        """Test that log_operation logs successful operations."""
        setup_logging(log_file=temp_log_file)

        with log_operation('test_operation', site_id='123'):
            pass  # Successful operation

        # Check log file
        with open(temp_log_file) as f:
            lines = f.readlines()

        # Find the completion log entry
        for line in lines:
            parsed = json.loads(line)
            if parsed.get('operation') == 'test_operation':
                assert parsed['status'] == 'success'
                assert 'duration_ms' in parsed
                assert parsed['site_id'] == '123'
                break
        else:
            pytest.fail('test_operation log entry not found')

    def test_log_operation_failure(self, clean_logging, temp_log_file):
        """Test that log_operation logs failed operations."""
        setup_logging(log_file=temp_log_file)

        with pytest.raises(ValueError):
            with log_operation('test_operation', site_id='123'):
                raise ValueError('Test error')

        # Check log file
        with open(temp_log_file) as f:
            lines = f.readlines()

        # Find the failure log entry
        for line in lines:
            parsed = json.loads(line)
            if parsed.get('operation') == 'test_operation':
                assert parsed['status'] == 'error'
                assert parsed['error'] == 'Test error'
                assert parsed['error_type'] == 'ValueError'
                assert 'traceback' in parsed
                break
        else:
            pytest.fail('test_operation log entry not found')


class TestRetryWithLogging:
    """Tests for the retry_with_logging decorator."""

    def test_retry_success_first_attempt(self, clean_logging, temp_log_file):
        """Test that successful operations don't log retries."""
        setup_logging(log_file=temp_log_file)

        @retry_with_logging(tries=3, delay=0.01)
        def successful_function():
            return 'success'

        result = successful_function()
        assert result == 'success'

        # Check that no retry logs were written
        with open(temp_log_file) as f:
            content = f.read()

        assert 'retry' not in content.lower()

    def test_retry_logs_attempts(self, clean_logging, temp_log_file):
        """Test that retry attempts are logged."""
        setup_logging(log_file=temp_log_file)

        attempt_count = [0]

        @retry_with_logging(tries=3, delay=0.01)
        def failing_then_success():
            attempt_count[0] += 1
            if attempt_count[0] < 2:
                raise ValueError('Temporary failure')
            return 'success'

        result = failing_then_success()
        assert result == 'success'
        assert attempt_count[0] == 2

        # Check for retry log
        with open(temp_log_file) as f:
            lines = f.readlines()

        found_retry = False
        for line in lines:
            parsed = json.loads(line)
            if parsed.get('operation') == 'retry':
                found_retry = True
                assert parsed['attempt'] == 2
                assert parsed['max_attempts'] == 3
                break

        assert found_retry, 'Retry log entry not found'

    def test_retry_exhausted(self, clean_logging, temp_log_file):
        """Test that exhausted retries are logged."""
        setup_logging(log_file=temp_log_file)

        @retry_with_logging(tries=2, delay=0.01)
        def always_failing():
            raise ValueError('Always fails')

        with pytest.raises(ValueError):
            always_failing()

        # Check for retry exhausted log
        with open(temp_log_file) as f:
            lines = f.readlines()

        found_exhausted = False
        for line in lines:
            parsed = json.loads(line)
            if parsed.get('operation') == 'retry_exhausted':
                found_exhausted = True
                assert parsed['attempts'] == 2
                assert parsed['error'] == 'Always fails'
                break

        assert found_exhausted, 'Retry exhausted log entry not found'


# Tests for Path Generation
# These will be added after refactoring the path functions in tesla_solar_download.py


class TestPathGeneration:
    """Tests for path generation functions."""

    def test_placeholder(self):
        """Placeholder test - will be implemented after path refactoring."""
        # TODO: Add tests for _get_energy_csv_name, _get_power_csv_name,
        # _get_soe_csv_name with output_dir parameter
        pass
