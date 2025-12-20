#!/usr/bin/env python3
"""Example log parser for Tesla download JSON logs.

This script demonstrates how to parse and analyze the structured JSON logs
produced by tesla_solar_download.py when run with --log-file option.

Usage:
    python3 parse_logs.py <log_file.jsonl>

Example:
    python3 parse_logs.py logs/download-20251220.jsonl
"""

import json
import sys
from collections import defaultdict
from datetime import datetime


def parse_log_file(log_file):
    """Parse a JSON lines log file and extract statistics.

    Args:
        log_file: Path to the .jsonl log file

    Returns:
        dict: Statistics extracted from the log file
    """
    stats = {
        'total_operations': 0,
        'successful_operations': 0,
        'failed_operations': 0,
        'downloads_by_type': defaultdict(int),
        'errors': [],
        'auth_info': None,
        'total_duration_ms': 0,
        'api_calls': 0,
        'files_downloaded': 0,
    }

    operations_by_type = defaultdict(list)

    try:
        with open(log_file) as f:
            for line_num, line in enumerate(f, 1):
                try:
                    entry = json.loads(line)

                    # Count total operations
                    if 'operation' in entry:
                        stats['total_operations'] += 1
                        op = entry['operation']
                        operations_by_type[op].append(entry)

                        # Track status
                        if entry.get('status') == 'success':
                            stats['successful_operations'] += 1
                        elif entry.get('status') == 'error':
                            stats['failed_operations'] += 1
                            stats['errors'].append({
                                'operation': op,
                                'error': entry.get('error'),
                                'timestamp': entry.get('timestamp')
                            })

                        # Track download types
                        if 'download' in op:
                            stats['files_downloaded'] += 1
                            if 'energy' in op:
                                stats['downloads_by_type']['energy'] += 1
                            elif 'power' in op:
                                stats['downloads_by_type']['power'] += 1
                            elif 'soe' in op:
                                stats['downloads_by_type']['soe'] += 1

                        # Sum durations
                        if 'duration_ms' in entry:
                            stats['total_duration_ms'] += entry['duration_ms']

                        # Track auth info
                        if op == 'auth_status':
                            stats['auth_info'] = {
                                'expires_at': entry.get('expires_at_human'),
                                'hours_until_expiry': entry.get('time_until_expiry_hours')
                            }

                except json.JSONDecodeError as e:
                    print(f"Warning: Invalid JSON on line {line_num}: {e}", file=sys.stderr)
                    continue

    except FileNotFoundError:
        print(f"Error: Log file not found: {log_file}", file=sys.stderr)
        sys.exit(1)
    except IOError as e:
        print(f"Error reading log file: {e}", file=sys.stderr)
        sys.exit(1)

    # Calculate success rate
    if stats['total_operations'] > 0:
        stats['success_rate'] = stats['successful_operations'] / stats['total_operations']
    else:
        stats['success_rate'] = 0

    return stats, operations_by_type


def print_summary(stats, operations_by_type):
    """Print a human-readable summary of the log statistics.

    Args:
        stats: Statistics dictionary
        operations_by_type: Dictionary of operations grouped by type
    """
    print("=" * 70)
    print("Tesla Solar Download Log Summary")
    print("=" * 70)
    print()

    # Overall stats
    print("Overall Statistics:")
    print(f"  Total Operations: {stats['total_operations']}")
    print(f"  Successful: {stats['successful_operations']}")
    print(f"  Failed: {stats['failed_operations']}")
    print(f"  Success Rate: {stats['success_rate']:.1%}")
    print(f"  Total Duration: {stats['total_duration_ms']/1000:.1f}s")
    print()

    # Download stats
    if stats['files_downloaded'] > 0:
        print("Downloads by Type:")
        for dtype, count in sorted(stats['downloads_by_type'].items()):
            print(f"  {dtype.capitalize()}: {count} files")
        print(f"  Total Files: {stats['files_downloaded']}")
        print()

    # Auth info
    if stats['auth_info']:
        print("Authentication:")
        print(f"  Token Expires: {stats['auth_info']['expires_at']}")
        print(f"  Hours Until Expiry: {stats['auth_info']['hours_until_expiry']:.1f}h")
        print()

    # Errors
    if stats['errors']:
        print(f"Errors ({len(stats['errors'])}):")
        for error in stats['errors'][:10]:  # Show first 10 errors
            print(f"  [{error['timestamp']}] {error['operation']}: {error['error']}")
        if len(stats['errors']) > 10:
            print(f"  ... and {len(stats['errors']) - 10} more errors")
        print()

    # Operation breakdown
    print("Operations Breakdown:")
    for op_type, entries in sorted(operations_by_type.items()):
        if entries:
            successes = sum(1 for e in entries if e.get('status') == 'success')
            failures = sum(1 for e in entries if e.get('status') == 'error')
            print(f"  {op_type}: {len(entries)} total ({successes} success, {failures} failed)")
    print()

    print("=" * 70)


def main():
    """Main entry point for the log parser."""
    if len(sys.argv) != 2:
        print("Usage: python3 parse_logs.py <log_file.jsonl>")
        print()
        print("Example:")
        print("  python3 parse_logs.py logs/download-20251220.jsonl")
        sys.exit(1)

    log_file = sys.argv[1]
    stats, operations = parse_log_file(log_file)
    print_summary(stats, operations)


if __name__ == '__main__':
    main()
