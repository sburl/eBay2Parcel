# eBay2Parcel

Automate tracking your eBay purchases in the Parcel app. This lightweight Python script fetches your recent eBay buyer orders, filters out delivered packages, and automatically adds tracking numbers to [Parcel](https://parcelapp.net/) so you can track all your shipments in one place.

## Features

- Fetches eBay orders from the last 90 days
- Automatically skips already-delivered shipments
- Deduplicates tracking numbers to avoid duplicates
- Supports multiple eBay accounts
- Respects Parcel API rate limits (configurable)
- Maps common carriers (USPS, UPS, FedEx, DHL, Amazon Logistics)
- Age-based filtering to skip old shipments

## Prerequisites

- Python 3.11 or higher
- eBay Developer Account with API credentials ([get them here](https://developer.ebay.com/))
- Parcel API key ([from Parcel app settings](https://parcelapp.net/))

## Installation

1. Clone this repository and navigate to the directory:
```bash
git clone https://github.com/yourusername/eBay2Parcel.git
cd eBay2Parcel
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
```

### Required Environment Variables

- `EBAY_APP_ID` - Your eBay App ID
- `EBAY_CLIENT_SECRET` - Your eBay Client Secret
- `EBAY_DEV_ID` - Your eBay Developer ID
- `EBAY_RUNAME` - Your eBay RuName (redirect URI)
- `EBAY_USER_TOKEN` - OAuth access token (auto-refreshed)
- `EBAY_REFRESH_TOKEN` - OAuth refresh token
- `PARCEL_API_KEY` - Your Parcel API key

### Optional Configuration

- `MAX_SHIPMENT_AGE_DAYS` (default: 45) - Skip pushing shipments older than this many days
- `PARCEL_MAX_PER_RUN` (default: 20) - Maximum tracking numbers to add per run
- For multiple eBay accounts, add suffixed variables: `EBAY_APP_ID_2`, `EBAY_CLIENT_SECRET_2`, etc.

## Getting OAuth Tokens

To obtain your initial eBay OAuth tokens, run the token generator:
```bash
python -m shared_ebay.generate_token
```

This helper will:
1. Guide you through browser-based OAuth authentication
2. Exchange the authorization code for access and refresh tokens
3. Automatically update your `.env` file

The auth helper is based on [eBayAPIHelpers](https://github.com/sburl/eBayAPIHelpers).

## Usage

Run the script manually:
```bash
python main.py
```

Or set up a cron job for automatic daily imports (example for 3:15 AM daily):
```bash
15 3 * * * cd /path/to/eBay2Parcel && /path/to/eBay2Parcel/venv/bin/python main.py >> cron.log 2>&1
```

### What it does:
- Fetches orders from the last 90 days
- Skips shipments already marked as delivered
- Filters out shipments older than `MAX_SHIPMENT_AGE_DAYS`
- Maps carrier names to Parcel's format
- Adds tracking numbers to Parcel
- Saves successfully added tracking numbers to `tracking_history.json`
- Stops on rate limit (429) and logs for retry

## Testing

Run the test suite:
```bash
python -m unittest test_integration.py
```

## Additional Documentation

See [`walkthrough.md`](walkthrough.md) for detailed setup instructions and troubleshooting.
