# eBay2Parcel

Lightweight script that pulls your recent eBay buyer orders, skips ones already delivered, and pushes tracking numbers into Parcel.

## Setup
1) Python 3.11+, then:
```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
2) Copy `.env.example` to `.env` and fill in:
- `EBAY_APP_ID`, `EBAY_CLIENT_SECRET`, `EBAY_DEV_ID`, `EBAY_RUNAME`
- `EBAY_USER_TOKEN`, `EBAY_REFRESH_TOKEN`
- `PARCEL_API_KEY`

## Refresh tokens (auth code)
If the refresh token expires, run the helper:
```
python -m shared_ebay.generate_token
```
It walks you through browser auth and updates `.env`.

## Run
```
python main.py
```
- Fetches last 30 days of orders, skips delivered shipments, maps common carriers, and posts to Parcel.
- Adds new tracking numbers to `tracking_history.json` to avoid duplicates.

## Tests
```
python -m unittest test_integration.py
```

More details: see `walkthrough.md`.
