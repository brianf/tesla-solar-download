#!/usr/bin/env python3
"""Configuration and statistics tracking for Tesla solar downloads."""


class DownloadStats:
    """Track download statistics for reporting."""

    def __init__(self):
        self.files_downloaded = 0
        self.files_skipped = 0
        self.files_failed = 0
        self.total_records = 0
        self.api_calls = 0
        self.total_duration_ms = 0
        self.errors = []

    def to_dict(self):
        """Convert stats to dictionary for logging.

        Returns:
            dict: Statistics as a dictionary with computed success rate.
        """
        total_attempts = self.files_downloaded + self.files_failed
        success_rate = (
            self.files_downloaded / total_attempts if total_attempts > 0 else 0
        )

        return {
            'files_downloaded': self.files_downloaded,
            'files_skipped': self.files_skipped,
            'files_failed': self.files_failed,
            'total_records': self.total_records,
            'api_calls': self.api_calls,
            'total_duration_ms': self.total_duration_ms,
            'success_rate': success_rate,
            'errors': len(self.errors),
        }
