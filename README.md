# Tesla Solar/Powerwall Data Downloader

## Introduction

This script will download your entire history of Tesla Solar power and energy data:
solar/battery/grid power data in 5 minute intervals, battery state of charge in 15 minute intervals,
and daily totals for solar/home/battery/grid energy.

The script is using the [unofficial Tesla API](https://tesla-api.timdorr.com/)
and [TeslaPy](https://github.com/tdorssers/TeslaPy) library.  Data is stored in CSV files: one file per
day for power, and one file per month for energy.  You can run the script repeatedly and it will only
download new data.

Note: if you're not comfortable running Python code and want better data exports from your Tesla solar/battery system,
consider the [Netzero app](https://www.netzero.energy).

## Installation

1. If needed, install Python 3 and git.
2. Clone the repo:
    ```bash
    git clone https://github.com/netzero-labs/tesla-solar-download.git
    cd tesla-solar-download
    ```

2. Install the package dependencies:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip3 install --upgrade pip
    pip3 install -r requirements.txt
    ```

## Usage
```bash
source venv/bin/activate
python3 ./tesla_solar_download.py --email my_tesla_email@gmail.com
```

Follow the instructions to log in to Tesla with your web browser (this is needed to generate an API
token, the credentials are only sent to Tesla).  Once you've logged in, the token will be stored
locally so you can rerun the script if needed.

Data will start downloading to the `download` directory.  Starting with today and going back in time
all the way to the Tesla system's installation date.

Power data downloads take ~1.5 seconds per day (~10 minutes per year of data).  This is mostly due
to delays used to slow down the rate of API requests.  You may interrupt and restart the process
-- any CSV files that already exist will be skipped during the next run.

Energy downloads are faster (less than 30s per year).


## Configuration Options

The script supports several command-line arguments for customization:

### Basic Options
- `--email`: (Required) Your Tesla account email address
- `--debug`: Enable debug output (timezone and date information)
- `--oldest-date`: Limit how far back to fetch data (YYYY-MM-DD format). Default: installation date

### Advanced Options
- `--output-dir`: Custom directory for downloaded CSV files. Default: `download`
- `--log-file`: Path to JSON log file for structured logging. Optional.
- `--non-interactive`: Exit with error code 2 if authentication required (for cron jobs)

### Examples

**Basic usage:**
```bash
python3 ./tesla_solar_download.py --email my_email@gmail.com
```

**Custom output directory:**
```bash
python3 ./tesla_solar_download.py --email my_email@gmail.com --output-dir /data/tesla
```

**With structured JSON logging:**
```bash
python3 ./tesla_solar_download.py --email my_email@gmail.com --log-file logs/download.jsonl
```

**For cron jobs (non-interactive mode):**
```bash
python3 ./tesla_solar_download.py --email my_email@gmail.com --non-interactive --log-file /var/log/tesla.jsonl
```

**Fetch only recent data:**
```bash
python3 ./tesla_solar_download.py --email my_email@gmail.com --oldest-date 2025-01-01
```


## Structured Logging

When you specify `--log-file`, the script writes detailed JSON logs that can be parsed and analyzed programmatically. This is especially useful for:
- Monitoring automated/cron downloads
- Debugging issues
- Tracking download statistics
- Web app integration

### Log Format

Each line in the log file is a JSON object with these common fields:
- `timestamp`: ISO 8601 timestamp with timezone
- `level`: Log level (INFO, WARNING, ERROR, DEBUG)
- `message`: Human-readable message
- `operation`: Type of operation being performed
- Additional context-specific fields

Example log entry:
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

### Parsing Logs

Use the included `parse_logs.py` script to analyze log files:

```bash
python3 parse_logs.py logs/download-20251220.jsonl
```

This will display:
- Success/failure statistics
- Download counts by type (energy, power, soe)
- Authentication token status
- Error summaries
- Total duration

For complete log format documentation, see [LOG_FORMAT.md](LOG_FORMAT.md).


## Token Management

### How Authentication Works

The script uses OAuth2 to authenticate with Tesla's API:
1. First run: You'll be prompted to log in via your web browser
2. After login, an authentication token is saved to `cache.json`
3. Subsequent runs: The token is loaded automatically (no login needed)
4. Token refresh: Access tokens expire after 8 hours but are automatically refreshed

### Token Storage

Authentication tokens are stored in `cache.json` in the project directory with:
- **Access token**: Short-lived (8 hours), used for API requests
- **Refresh token**: Long-lived (weeks/months), used to obtain new access tokens
- **Expiration timestamp**: When the access token expires

**Important:** Keep `cache.json` secure! Anyone with this file can access your Tesla account data.

### Token Expiration & Renewal

The refresh token allows unattended operation for weeks or months. However, if the refresh token expires:
1. The script will detect authentication failure
2. In interactive mode: You'll be prompted to log in again
3. In `--non-interactive` mode: Script exits with code 2

### Renewing Tokens for Cron Jobs

When running as a cron job, if authentication fails:

1. **Detect the failure**: Check cron job exit code (exit code 2 = auth needed)
2. **Run locally**: Execute the script on your local machine:
   ```bash
   python3 tesla_solar_download.py --email your_email@example.com
   ```
3. **Complete browser login**: Follow the interactive prompts
4. **Upload new token**: Copy the updated `cache.json` to your server
5. **Resume cron**: Next scheduled run will succeed with fresh tokens

For SolarTracker integration, you can upload `cache.json` via the web UI file manager.


## Integration with SolarTracker

This script is designed to work seamlessly with the SolarTracker web application.

### Cron Job Setup

Add to your crontab for automatic daily downloads:
```bash
# Run Tesla download daily at 2 AM
0 2 * * * cd /path/to/tesla-solar-download && python3 tesla_solar_download.py --email your@email.com --output-dir /data/solar/tesla --log-file /var/log/tesla-$(date +\%Y\%m\%d).jsonl --non-interactive
```

### Monitoring Downloads

The SolarTracker web app can:
1. Parse JSON logs using `parse_logs.py` to display download statistics
2. Monitor for authentication failures (exit code 2)
3. Alert admins when token renewal is needed
4. Provide UI for uploading renewed `cache.json`

### Log Analysis

Your web app can parse the JSON logs to extract:
- Last successful download time
- Files downloaded per day/month
- API errors and warnings
- Token expiration countdown
- Download performance metrics

See `parse_logs.py` for a reference implementation of log parsing.


## Data

Power data is formatted as follows:
`download/<site_id>/power/2022-07-19.csv`
```CSV
timestamp,solar_power,battery_power,grid_power,load_power
[...]
2023-07-19 10:40:00,7506.428571428572,-7401.224489795918,612.5714285714286,717.775510204082
2023-07-19 10:45:00,7576.836734693878,-3342.0408163265306,-3555.030612244898,679.7653061224487
2023-07-19 10:50:00,7616.666666666667,-3466.6666666666665,-3544.4,605.5999999999999
[...]
```

- One CSV file per day.
- Every file starts at midnight and ends at 11.55pm, in 5 minute increments.
- All power values are in Watts. Note: to get Watt-hour energy values for the 5-minute interval, divide the value by 12. You can then add up all the values and divide by 1000 for the daily kWh total.
- load_power is simply a sum of solar+battery+grid+generator power and is what is shown as "house" load in the Tesla app.  (Note: this value is not included in API responses since it can be easily derived.)

Energy data:
`download/<site_id>/energy/2022-07.csv`
```CSV
timestamp,solar_energy_exported,grid_energy_imported,grid_energy_exported_from_solar,grid_energy_exported_from_battery,battery_energy_exported,battery_energy_imported_from_grid,battery_energy_imported_from_solar,consumer_energy_imported_from_grid,consumer_energy_imported_from_solar,consumer_energy_imported_from_battery
2023-07-01 01:00:00,66700,6493.5,43456,0,16760,249.5,15640.5,6244,7603.5,16760
2023-07-02 01:00:00,66780,6353,40874,0,14060,260,18510,6093,7396,14060
2023-07-03 01:00:00,67380,6282,45964.5,0,10030,230,15580,6052,5835.5,10030
[...]
```

Powerwall state of charge data:
`download/<site_id>/soe/2022-07-19.csv`
```CSV
timestamp,soe
2024-07-19 00:00:00,44
2024-07-19 00:15:00,43
2024-07-19 00:30:00,43
[...]
```
