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
- Multi-account: add suffixed vars (`EBAY_APP_ID_2`, `EBAY_CLIENT_SECRET_2`, `EBAY_DEV_ID_2`, `EBAY_RUNAME_2`, `EBAY_USER_TOKEN_2`, `EBAY_REFRESH_TOKEN_2`, etc.). Defaults use the unsuffixed set.
- Optional: `MAX_SHIPMENT_AGE_DAYS` (default 45) to skip pushing older likely-delivered shipments.
- Optional: `PARCEL_MAX_PER_RUN` (default 20) to cap calls per run and avoid rate limits.

## Refresh tokens (auth code)
If the refresh token expires, run the helper:
```
python -m shared_ebay.generate_token
```
It walks you through browser auth and updates `.env`.
Helper/auth code lives in https://github.com/sburl/eBayAPIHelpers if you need to inspect it.

## Run
```
python main.py
```
- Fetches last 90 days of orders, skips delivered shipments, maps common carriers, and posts to Parcel.
- Adds new tracking numbers to `tracking_history.json` to avoid duplicates.
- Parcel free tier rate-limits (20/day); on 429 the script stops sending further requests for that run.

## Tests
```
python -m unittest test_integration.py
```

More details: see `walkthrough.md`.
