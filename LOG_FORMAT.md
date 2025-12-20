# Tesla Solar Download - Log Format Specification

This document describes the JSON log format used by `tesla_solar_download.py` when run with the `--log-file` option.

## Overview

The log file uses JSON Lines format (`.jsonl`):
- Each line is a separate, valid JSON object
- Lines are independent (one malformed line doesn't corrupt the file)
- Easy to parse line-by-line for streaming analysis
- Compatible with tools like `jq`, `grep`, and custom parsers

## Common Fields

Every log entry includes these base fields:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 timestamp with timezone (UTC) |
| `level` | string | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `message` | string | Human-readable message describing the event |

## Operation-Specific Fields

Additional fields are included based on the `operation` type:

### Startup (`operation: "startup"`)

Logged when the script starts.

```json
{
  "timestamp": "2025-12-20T10:30:00.000Z",
  "level": "INFO",
  "message": "Tesla Solar Download starting",
  "operation": "startup",
  "email": "user@example.com",
  "output_dir": "download",
  "log_file": "console_only",
  "non_interactive": false
}
```

**Fields:**
- `email`: Tesla account email (for identification)
- `output_dir`: Base directory for CSV files
- `log_file`: Log file path or "console_only"
- `non_interactive`: Whether running in non-interactive mode

### Authentication Status (`operation: "auth_status"`)

Logged after successful authentication.

```json
{
  "timestamp": "2025-12-20T10:30:05.000Z",
  "level": "INFO",
  "message": "Authenticated successfully",
  "operation": "auth_status",
  "expires_at": 1734705000.0,
  "expires_at_human": "Fri Dec 20 16:30:00 2025",
  "time_until_expiry_hours": 5.7,
  "cache_file": "cache.json"
}
```

**Fields:**
- `expires_at`: Unix timestamp when access token expires
- `expires_at_human`: Human-readable expiration time
- `time_until_expiry_hours`: Hours until token expires
- `cache_file`: Location of authentication cache

### Authentication Required (`operation: "auth_required"`)

Logged when running in non-interactive mode and authentication is needed.

```json
{
  "timestamp": "2025-12-20T10:30:00.000Z",
  "level": "ERROR",
  "message": "Authentication required - not authorized",
  "operation": "auth_required",
  "auth_url": "https://auth.tesla.com/...",
  "cache_file": "cache.json",
  "instructions": "Run script locally to authenticate, then upload cache.json"
}
```

**Fields:**
- `auth_url`: OAuth2 authorization URL for browser login
- `cache_file`: Where tokens are stored
- `instructions`: Steps to renew authentication

### Download Operations (`operation: "download_energy_month"`, `"download_power_day"`, `"download_soe_day"`)

Logged when downloading data files.

```json
{
  "timestamp": "2025-12-20T10:30:45.123Z",
  "level": "INFO",
  "message": "download_energy_month completed",
  "operation": "download_energy_month",
  "site_id": "***1234",
  "date": "2025-12",
  "duration_ms": 1234,
  "records": 31,
  "file": "download/12345/energy/2025-12.csv",
  "status": "success"
}
```

**Fields:**
- `operation`: Type of download (energy, power, or soe)
- `site_id`: Obfuscated Tesla site ID (last 4 digits)
- `date`: Date/month being downloaded (format varies by operation)
- `duration_ms`: Time taken in milliseconds
- `records`: Number of data records downloaded
- `file`: Path to the created CSV file
- `status`: `"success"` or `"error"`

**Date Formats:**
- Energy: `"YYYY-MM"` (monthly)
- Power/SOE: `"YYYY-MM-DD"` (daily)

### Retry Operations (`operation: "retry"`)

Logged when an operation is being retried.

```json
{
  "timestamp": "2025-12-20T10:31:00.000Z",
  "level": "WARNING",
  "message": "Retry attempt 2/3 for _download_energy_month",
  "operation": "retry",
  "function": "_download_energy_month",
  "attempt": 2,
  "max_attempts": 3
}
```

**Fields:**
- `function`: Name of the function being retried
- `attempt`: Current attempt number
- `max_attempts`: Total attempts before giving up

### Retry Exhausted (`operation: "retry_exhausted"`)

Logged when all retry attempts have failed.

```json
{
  "timestamp": "2025-12-20T10:31:10.000Z",
  "level": "ERROR",
  "message": "All 3 attempts failed for _download_energy_month",
  "operation": "retry_exhausted",
  "function": "_download_energy_month",
  "attempts": 3,
  "error": "Connection timeout",
  "error_type": "ConnectionError"
}
```

**Fields:**
- `function`: Name of the function that failed
- `attempts`: Number of attempts made
- `error`: Error message from last attempt
- `error_type`: Python exception class name

### Logging Initialization (`operation: "logging_init"`)

Logged when file logging is successfully enabled.

```json
{
  "timestamp": "2025-12-20T10:30:00.100Z",
  "level": "INFO",
  "message": "Structured logging enabled to logs/download.jsonl",
  "operation": "logging_init",
  "log_file": "logs/download.jsonl"
}
```

**Fields:**
- `log_file`: Path to the log file

### Error Operations

Any operation can fail and log an error entry with additional error fields.

```json
{
  "timestamp": "2025-12-20T10:32:00.000Z",
  "level": "ERROR",
  "message": "download_energy_month failed",
  "operation": "download_energy_month",
  "site_id": "***1234",
  "date": "2025-12",
  "duration_ms": 456,
  "status": "error",
  "error": "API rate limit exceeded",
  "error_type": "RateLimitError",
  "traceback": "Traceback (most recent call last):\n  File..."
}
```

**Additional Error Fields:**
- `status`: Always `"error"` for failed operations
- `error`: Error message
- `error_type`: Exception class name
- `traceback`: Full Python traceback (for debugging)

## Parsing Examples

### Using Python

```python
import json

with open('download.jsonl') as f:
    for line in f:
        entry = json.loads(line)
        if entry['level'] == 'ERROR':
            print(f"Error: {entry['message']}")
```

### Using jq

```bash
# Extract all errors
jq 'select(.level == "ERROR")' download.jsonl

# Count successful downloads
jq 'select(.status == "success")' download.jsonl | wc -l

# Get auth token expiration
jq 'select(.operation == "auth_status") | .expires_at_human' download.jsonl

# Calculate average download time
jq 'select(.status == "success") | .duration_ms' download.jsonl | \
  awk '{sum+=$1; count++} END {print sum/count}'
```

### Using grep

```bash
# Find authentication errors
grep "auth_required" download.jsonl

# Find all errors
grep '"level":"ERROR"' download.jsonl

# Find specific site downloads
grep '"site_id":"***1234"' download.jsonl
```

## Query Patterns

### Common Analysis Tasks

**Check if authentication is needed:**
```bash
grep "auth_required" download.jsonl && echo "Auth needed!" || echo "Auth OK"
```

**Count downloads by type:**
```bash
grep "download_energy_month" download.jsonl | wc -l  # Energy downloads
grep "download_power_day" download.jsonl | wc -l     # Power downloads
grep "download_soe_day" download.jsonl | wc -l       # SOE downloads
```

**Find failed operations:**
```bash
jq 'select(.status == "error") | {operation, error, date}' download.jsonl
```

**Get last download time:**
```bash
tail -1 download.jsonl | jq '.timestamp'
```

**Calculate total runtime:**
```bash
# First timestamp
START=$(head -1 download.jsonl | jq -r '.timestamp' | date -f - +%s)
# Last timestamp
END=$(tail -1 download.jsonl | jq -r '.timestamp' | date -f - +%s)
# Duration
echo "$((END - START)) seconds"
```

## Log Rotation

Since logs can grow large, consider rotating them:

**By date (in cron):**
```bash
--log-file /var/log/tesla/download-$(date +%Y%m%d).jsonl
```

**Manual cleanup:**
```bash
# Keep last 30 days
find /var/log/tesla -name "*.jsonl" -mtime +30 -delete
```

**Using logrotate:**
```
/var/log/tesla/*.jsonl {
    daily
    rotate 30
    compress
    missingok
    notifempty
}
```

## Integration with Monitoring Systems

### Prometheus/Grafana

Convert logs to Prometheus metrics:
```python
# Count successes/failures
success_count = sum(1 for entry in logs if entry.get('status') == 'success')
error_count = sum(1 for entry in logs if entry.get('status') == 'error')

# Average duration
durations = [e['duration_ms'] for e in logs if 'duration_ms' in e]
avg_duration = sum(durations) / len(durations)
```

### Alerting

Set up alerts for:
- `auth_required` operation (token renewal needed)
- High error rates (> 10% of operations)
- Missing downloads (no logs in 24 hours)
- Slow downloads (duration > threshold)

Example alert script:
```bash
#!/bin/bash
if grep -q "auth_required" /var/log/tesla/download.jsonl; then
    echo "Tesla auth token expired!" | mail -s "Alert" admin@example.com
fi
```

## Best Practices

1. **One log file per run**: Use timestamps in filename for natural rotation
2. **Parse incrementally**: Process logs line-by-line for large files
3. **Handle invalid JSON**: Use try/catch when parsing (malformed lines possible)
4. **Index by timestamp**: For time-based queries, index on the timestamp field
5. **Compress old logs**: gzip files older than 7 days
6. **Monitor file size**: Alert if logs grow unexpectedly large (indicates issues)

## See Also

- [README.md](README.md) - Main documentation
- [parse_logs.py](parse_logs.py) - Reference log parser implementation
- [tesla_solar_download.py](tesla_solar_download.py) - Main script
- [structured_logger.py](structured_logger.py) - Logging implementation
