# eBay2Parcel Walkthrough

## What this project does
- Pulls your recent eBay orders as a buyer and extracts shipment tracking info.
- Pushes each tracking number into Parcel via its external API.
- Persists already-sent tracking numbers in `tracking_history.json` so reruns stay idempotent.

## Prerequisites
- Python 3.11+ with `pip`.
- eBay Developer keys (App ID, Client Secret, Dev ID, RuName redirect).
- Parcel API key.

## Setup
1) Create and activate a virtualenv (recommended):
```
python -m venv venv
source venv/bin/activate
```
2) Install dependencies:
```
pip install -r requirements.txt
```
3) Create `.env` in the repo root (already present for me) and set:
```
EBAY_APP_ID=
EBAY_CLIENT_SECRET=
EBAY_DEV_ID=
EBAY_RUNAME=                     # eBay redirect/RuName value
EBAY_USER_TOKEN=                 # Access token; auto-refreshed when present
EBAY_REFRESH_TOKEN=              # Refresh token returned by OAuth
PARCEL_API_KEY=
```
Keep `.env` out of version control.

## Getting eBay OAuth tokens (one-time)
The `shared_ebay.auth` helper will refresh tokens automatically, but you need an initial refresh token.

Helper library is installed from `https://github.com/sburl/eBayAPIHelpers.git` via `requirements.txt`.

1) Build an authorization URL (uses your RuName redirect):
```
python - <<'PY'
import os, urllib.parse
scopes = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/buy.order",
    "https://api.ebay.com/oauth/api_scope/sell.marketing.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
]
base = "https://auth.ebay.com/oauth2/authorize"
params = {
    "client_id": os.environ["EBAY_APP_ID"],
    "redirect_uri": os.environ["EBAY_RUNAME"],
    "response_type": "code",
    "scope": " ".join(scopes),
}
qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
print(f"{base}?{qs}")
PY
```
2) Open the printed URL in a browser, sign in with the eBay buyer account you want, approve the scopes, and copy the `code` query parameter from the redirect.
3) Exchange that code for tokens (writes nothing to disk):
```
AUTH=$(printf "%s:%s" "$EBAY_APP_ID" "$EBAY_CLIENT_SECRET" | base64)
curl -X POST https://api.ebay.com/identity/v1/oauth2/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Authorization: Basic $AUTH" \
  -d "grant_type=authorization_code&code=PASTE_CODE_HERE&redirect_uri=$EBAY_RUNAME"
```
4) From the JSON response, copy `refresh_token` (and `access_token` if present) into your `.env` as `EBAY_REFRESH_TOKEN` and `EBAY_USER_TOKEN`. Subsequent runs will refresh automatically and update `.env` via `shared_ebay.auth.ensure_valid_token()`.

## Running the importer
```
python main.py
```
- Fetches up to 90 days of orders, extracts tracking info, skips delivered shipments, maps common carriers (USPS/UPS/FedEx/DHL/Amazon), and posts to Parcel.
- Successful posts are logged and tracking numbers are added to `tracking_history.json` to avoid duplicates on the next run.
- Parcel free tier rate-limits (20/day); if a 429 is encountered, the script stops further requests for that run and logs the tracking number so you can retry later.
- Set `MAX_SHIPMENT_AGE_DAYS` (default 45) to skip pushing older likely-delivered shipments.

### Cron-friendly usage
Example daily run at 3:15 AM (update paths as needed):
```
15 3 * * * cd /Users/you/Developer/eBay2Parcel && /Users/you/Developer/eBay2Parcel/venv/bin/python main.py >> /Users/you/Developer/eBay2Parcel/cron.log 2>&1
```
Use the venv’s Python path if you installed dependencies there.

### Refreshing tokens with an auth code
If your refresh token expires, re-authorize and then run the helper from the pip repo:
```
python -m shared_ebay.generate_token
```
Requires `EBAY_APP_ID`, `EBAY_CLIENT_SECRET`, and `EBAY_RUNAME` in `.env`. The script walks you through the browser auth, exchanges the code, and updates `EBAY_USER_TOKEN` / `EBAY_REFRESH_TOKEN` in `.env`.

### Multiple eBay accounts
Add suffixed env vars (`EBAY_APP_ID_2`, `EBAY_CLIENT_SECRET_2`, `EBAY_DEV_ID_2`, `EBAY_RUNAME_2`, `EBAY_USER_TOKEN_2`, `EBAY_REFRESH_TOKEN_2`, etc.). The script will process the default account and then each numbered account in order.

### Throttling and age limits
- `PARCEL_MAX_PER_RUN` (default 20) caps attempts per run; script stops once reached or on a 429.
- `MAX_SHIPMENT_AGE_DAYS` (default 45) skips pushing older likely-delivered shipments.

## Verification / tests
```
python -m unittest test_integration.py
```
This covers tracking extraction and the Parcel client request shape. For live eBay/Parcel calls, rely on the runtime logs while running `main.py`.
