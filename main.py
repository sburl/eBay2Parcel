import os
import sys
import json
import requests
import logging
import argparse
import fcntl
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from ebaysdk.trading import Connection as Trading
from ebaysdk.exception import ConnectionError

# Try importing shared_ebay, with fallback to local APIHelpers
try:
    from shared_ebay.auth import ensure_valid_token, get_token_manager
except ImportError:
    # Fallback to local APIHelpers repo if not installed
    EBAY2PARCEL_ROOT = Path(__file__).resolve().parent
    APIHELPERS_SRC = EBAY2PARCEL_ROOT.parent / "APIHelpers" / "src"
    if APIHELPERS_SRC.exists():
        sys.path.insert(0, str(APIHELPERS_SRC))
        from shared_ebay.auth import ensure_valid_token, get_token_manager
    else:
        raise ImportError("shared_ebay not found. Install with: pip install git+https://github.com/sburl/eBayAPIHelpers.git")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def _env_key(base: str, suffix: str) -> str:
    return f"{base}_{suffix}" if suffix else base


class EbayClient:
    def __init__(self, suffix: str = ""):
        # Ensure we have a valid token before starting
        if not ensure_valid_token(suffix=suffix):
            raise Exception(f"Failed to obtain valid eBay token for suffix '{suffix}'")
            
        self.token = get_token_manager(suffix=suffix).get_current_token()
        self.api = Trading(
            appid=os.getenv(_env_key("EBAY_APP_ID", suffix)),
            certid=os.getenv(_env_key("EBAY_CLIENT_SECRET", suffix)), # ebaysdk uses certid for client secret in some contexts
            devid=os.getenv(_env_key("EBAY_DEV_ID", suffix)),
            token=self.token,
            config_file=None,
            domain="api.ebay.com"
        )

    def get_recent_orders(self, days_back=90):
        """Fetch orders from the last N days where the user is the buyer."""
        try:
            # Calculate time range
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=days_back)
            
            # Format dates for eBay API (ISO 8601)
            # Trading API expects: YYYY-MM-DDTHH:MM:SS.SSSZ
            create_time_from = start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            create_time_to = end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            response = self.api.execute('GetOrders', {
                'CreateTimeFrom': create_time_from,
                'CreateTimeTo': create_time_to,
                'OrderRole': 'Buyer',
                'DetailLevel': 'ReturnAll'
            })
            
            data = response.dict()
            ack = data.get('Ack')
            if ack != 'Success':
                logger.warning(f"GetOrders returned Ack={ack} Errors={data.get('Errors')}")
            order_array = data.get('OrderArray', {}).get('Order', [])
            if isinstance(order_array, dict):
                order_array = [order_array]
            logger.info(f"GetOrders retrieved {len(order_array)} orders")
            return data
            
        except ConnectionError as e:
            logger.error(f"eBay API Connection Error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return None

class ParcelClient:
    def __init__(self, dry_run=False):
        self.api_key = os.getenv("PARCEL_API_KEY")
        self.base_url = "https://api.parcel.app/external/add-delivery/"
        self.dry_run = dry_run

        if not self.api_key and not dry_run:
            logger.warning("PARCEL_API_KEY not found in environment variables")

        if dry_run:
            logger.info("🔍 DRY-RUN MODE: No API calls will be made to Parcel")

    def add_delivery(self, tracking_number, carrier_code, description):
        """Add a delivery to Parcel app.

        Args:
            tracking_number: Tracking number to add
            carrier_code: Carrier code (usps, ups, fedex, etc.)
            description: Description for the shipment

        Returns:
            (success: bool, rate_limited: bool)
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would add to Parcel: {tracking_number} ({carrier_code}) - {description}")
            return True, False

        if not self.api_key:
            logger.error("Cannot add delivery: Missing Parcel API Key")
            return False, False

        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        data = {
            "tracking_number": tracking_number,
            "carrier_code": carrier_code,
            "description": description,
            "send_push_confirmation": True
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=data)
            error_message = None
            try:
                error_json = response.json()
                error_message = error_json.get("error_message") or error_json.get("message")
            except Exception:
                error_json = None

            if response.status_code == 200:
                logger.info(f"Successfully added {tracking_number} to Parcel")
                return True, False

            if response.status_code == 400 and error_message:
                lower = error_message.lower()
                if "already added" in lower:
                    logger.info(f"{tracking_number} already exists in Parcel; skipping")
                    return True, False  # Treat as handled so we add to history and avoid retrying
                if "unsupported carrier" in lower:
                    logger.error(f"Unsupported carrier for {tracking_number}; please add manually. Message: {error_message}")
                    return False, False

            if response.status_code == 429:
                logger.error(f"Rate limited by Parcel while adding {tracking_number}; stopping further requests. Message: {error_message or response.text}")
                return False, True

            logger.error(
                f"Failed to add delivery. Status: {response.status_code}, "
                f"Error: {error_message or response.text}"
            )
            return False, False
                
        except Exception as e:
            logger.error(f"Error adding delivery to Parcel: {e}")
            return False, False

def load_history():
    if os.path.exists("tracking_history.json"):
        try:
            with open("tracking_history.json", "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_history(history, dry_run=False):
    """
    Save tracking history to file with atomic write and file locking.

    Uses a temporary file + atomic rename to prevent corruption,
    and file locking to prevent concurrent writes.

    Args:
        history: List of tracking history dicts
        dry_run: If True, only log what would be saved

    Returns:
        bool: True if successful
    """
    if dry_run:
        logger.info(f"[DRY-RUN] Would save {len(history)} items to tracking_history.json")
        return True

    history_file = "tracking_history.json"

    try:
        # Create temp file in same directory for atomic rename
        temp_fd, temp_path = tempfile.mkstemp(
            dir=os.path.dirname(history_file) or '.',
            prefix='.tracking_history_',
            suffix='.tmp'
        )

        try:
            # Acquire exclusive lock on temp file
            fcntl.flock(temp_fd, fcntl.LOCK_EX)

            # Write to temp file
            with os.fdopen(temp_fd, 'w') as f:
                json.dump(history, f, indent=2)

            # Atomic rename (replaces existing file)
            os.rename(temp_path, history_file)
            logger.debug(f"Successfully saved {len(history)} items to {history_file}")
            return True

        except Exception as e:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise e

    except Exception as e:
        logger.error(f"Error saving history: {e}")
        return False

def _delivered_tracking_numbers(order):
    """Collect tracking numbers already marked delivered via shipment details."""
    delivered = set()
    shipments = order.get('ShipmentArray', {}).get('Shipment', [])
    if isinstance(shipments, dict):
        shipments = [shipments]

    for shipment in shipments:
        shipment_status = shipment.get('Status')
        shipment_delivered_time = shipment.get('ActualDeliveryDate') or shipment.get('DeliveryDate')
        shipment_marked_delivered = False
        if shipment_status and 'delivered' in str(shipment_status).lower():
            shipment_marked_delivered = True
        if shipment_delivered_time:
            shipment_marked_delivered = True

        tracking_details = shipment.get('ShipmentTrackingDetails') or []
        if isinstance(tracking_details, dict):
            tracking_details = [tracking_details]

        for tracking in tracking_details:
            tracking_number = tracking.get('ShipmentTrackingNumber')
            if not tracking_number:
                continue

            delivered_flag = shipment_marked_delivered
            delivery_status = tracking.get('DeliveryStatus') or tracking.get('Status')
            delivered_time = tracking.get('ActualDeliveryDate') or tracking.get('DeliveryDate')
            if delivery_status and 'delivered' in str(delivery_status).lower():
                delivered_flag = True
            if delivered_time:
                delivered_flag = True

            if delivered_flag:
                delivered.add(tracking_number)

    return delivered

def extract_tracking_info(orders):
    """Extract tracking numbers and carrier info from orders, skipping delivered/old shipments."""
    shipments = []
    delivered_skipped = 0
    aged_skipped = 0
    max_age_days = int(os.getenv("MAX_SHIPMENT_AGE_DAYS", "45"))
    
    if not orders or 'OrderArray' not in orders or not orders['OrderArray']:
        return shipments, delivered_skipped, aged_skipped
        
    order_list = orders['OrderArray'].get('Order', [])
    if isinstance(order_list, dict):
        order_list = [order_list]
        
    for order in order_list:
        # Approximate age to avoid pushing very old (likely delivered) shipments
        order_time_str = order.get('ShippedTime') or order.get('PaidTime') or order.get('CreatedTime')
        if order_time_str:
            try:
                # eBay uses ISO-like with Z
                order_time = datetime.fromisoformat(order_time_str.replace('Z', '+00:00'))
                if (datetime.now(timezone.utc) - order_time).days > max_age_days:
                    aged_skipped += 1
                    continue
            except Exception:
                pass

        delivered_numbers = _delivered_tracking_numbers(order)

        # Check for shipping details
        if 'ShippingDetails' in order:
            shipping_details = order['ShippingDetails']
            tracking_details = shipping_details.get('ShipmentTrackingDetails') or []
            # Some responses use ShipmentLineItemArray.Transaction.ShippingDetails.ShipmentTrackingDetails
            if not tracking_details:
                txns = order.get('TransactionArray', {}).get('Transaction', [])
                if isinstance(txns, dict):
                    txns = [txns]
                for txn in txns:
                    sd = txn.get('ShippingDetails', {})
                    td = sd.get('ShipmentTrackingDetails') or []
                    if td:
                        tracking_details = td
                        break

            if isinstance(tracking_details, dict):
                tracking_details = [tracking_details]

            for tracking in tracking_details:
                tracking_number = tracking.get('ShipmentTrackingNumber')
                carrier = tracking.get('ShippingCarrierUsed') or tracking.get('ShippingCarrierCode')
                
                # Skip already delivered shipments based on status or delivery date
                delivered_flag = False
                if tracking_number in delivered_numbers:
                    delivered_flag = True
                else:
                    delivery_status = tracking.get('DeliveryStatus') or tracking.get('Status')
                    delivered_time = tracking.get('ActualDeliveryDate') or tracking.get('DeliveryDate')
                    if delivery_status:
                        delivered_flag = 'delivered' in str(delivery_status).lower()
                    if delivered_time:
                        delivered_flag = True
                if delivered_flag:
                    delivered_skipped += 1
                    continue
                
                # Get item title for description
                title = "eBay Item"
                if 'TransactionArray' in order and 'Transaction' in order['TransactionArray']:
                    transactions = order['TransactionArray']['Transaction']
                    if isinstance(transactions, dict):
                        transactions = [transactions]
                    if transactions:
                        title = transactions[0].get('Item', {}).get('Title', 'eBay Item')
                        # Truncate title if too long
                        if len(title) > 30:
                            title = title[:27] + "..."

                if tracking_number:
                    shipments.append({
                        'tracking_number': tracking_number,
                        'carrier': carrier,
                        'description': title
                    })
                    
    return shipments, delivered_skipped, aged_skipped

def _account_suffixes():
    """Collect configured account suffixes: default, then _2, _3, ..."""
    suffixes = []
    if os.getenv('EBAY_APP_ID'):
        suffixes.append("")
    # Numeric suffixes starting at 2 (EBAY_APP_ID_2, EBAY_APP_ID_3, ...)
    i = 2
    while True:
        if os.getenv(f'EBAY_APP_ID_{i}'):
            suffixes.append(str(i))
            i += 1
            continue
        break
    return suffixes


def process_account(suffix: str, history, history_tracking_numbers, days_back: int = 90, dry_run: bool = False):
    label = f"default" if not suffix else f"account {suffix}"
    logger.info(f"[{label}] Initializing clients...")
    try:
        ebay = EbayClient(suffix=suffix)
        parcel = ParcelClient(dry_run=dry_run)
    except Exception as e:
        logger.critical(f"[{label}] Initialization failed: {e}")
        return 0
    if not parcel.api_key and not dry_run:
        logger.critical(f"[{label}] PARCEL_API_KEY missing; aborting before any Parcel calls.")
        return 0

    logger.info(f"[{label}] Fetching recent orders from eBay (last {days_back} days)...")
    orders = ebay.get_recent_orders(days_back=days_back)
    
    if not orders:
        logger.info(f"[{label}] No orders found or error fetching orders.")
        return 0
    
    order_list = orders.get('OrderArray', {}).get('Order', [])
    if isinstance(order_list, dict):
        order_list = [order_list]
    logger.info(f"[{label}] Processing {len(order_list)} orders for tracking extraction")

    shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)
    total_with_tracking = len(shipments) + delivered_skipped + aged_skipped
    logger.info(
        f"[{label}] Found {total_with_tracking} shipments with tracking info "
        f"(skipped {delivered_skipped} delivered, {aged_skipped} older than MAX_SHIPMENT_AGE_DAYS)."
    )

    new_shipments_count = 0
    history_set = set(history_tracking_numbers)
    run_seen = set()
    max_per_run = int(os.getenv("PARCEL_MAX_PER_RUN", "20"))
    attempts = 0
    
    for shipment in shipments:
        tracking_number = shipment['tracking_number']
        if tracking_number in history_set or tracking_number in run_seen:
            logger.debug(f"[{label}] Skipping existing tracking number: {tracking_number}")
            continue
        run_seen.add(tracking_number)
        if attempts >= max_per_run:
            logger.info(f"[{label}] Reached PARCEL_MAX_PER_RUN={max_per_run}; stopping further requests.")
            break
            
        carrier_code = shipment.get('carrier', 'pholder') 
        
        carrier_map = {
            'USPS': 'usps',
            'UPS': 'ups',
            'FedEx': 'fedex',
            'DHL': 'dhl',
            'Amazon': 'amazon-logistics'
        }
        
        normalized_carrier = carrier_code.upper() if carrier_code else ""
        for key, value in carrier_map.items():
            if key in normalized_carrier:
                carrier_code = value
                break
        
        success, rate_limited = parcel.add_delivery(
            tracking_number=tracking_number,
            carrier_code=carrier_code,
            description=shipment['description']
        )
        attempts += 1
        
        if rate_limited:
            logger.error(f"[{label}] Hit Parcel rate limit; stopping further requests for this run.")
            break

        if success:
            history.append({
                'tracking_number': tracking_number,
                'added_at': datetime.now(timezone.utc).isoformat()
            })
            history_set.add(tracking_number)
            history_tracking_numbers.append(tracking_number)
            new_shipments_count += 1
            
    return new_shipments_count


def main():
    parser = argparse.ArgumentParser(
        description="eBay2Parcel: Automatically sync eBay shipments to Parcel app",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Normal mode: sync shipments to Parcel
  %(prog)s --dry-run          # Dry-run: show what would be synced without making API calls
  %(prog)s --days-back 30     # Only sync shipments from last 30 days

Environment Variables:
  EBAY_APP_ID                 # eBay App ID (required)
  EBAY_CLIENT_SECRET          # eBay Client Secret (required)
  EBAY_USER_TOKEN             # eBay User Token (required)
  PARCEL_API_KEY              # Parcel API Key (required unless --dry-run)
  MAX_SHIPMENT_AGE_DAYS       # Max age for shipments (default: 45)
        """
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be synced without making any API calls to Parcel (safe for testing)'
    )
    parser.add_argument(
        '--days-back',
        type=int,
        default=90,
        help='Number of days back to fetch orders (default: 90)'
    )

    args = parser.parse_args()

    if args.dry_run:
        print("=" * 60)
        print("🔍 DRY-RUN MODE ENABLED")
        print("No changes will be made to Parcel")
        print("=" * 60)
    else:
        print("Starting eBay2Parcel...")

    history = load_history()
    history_tracking_numbers = [item['tracking_number'] for item in history]

    suffixes = _account_suffixes()
    if not suffixes:
        logger.critical("No EBAY_APP_ID configured in environment")
        return

    total_added = 0
    for suffix in suffixes:
        added = process_account(
            suffix,
            history,
            history_tracking_numbers,
            days_back=args.days_back,
            dry_run=args.dry_run
        )
        total_added += added

    if total_added > 0:
        if save_history(history, dry_run=args.dry_run):
            if args.dry_run:
                logger.info(f"[DRY-RUN] Would add {total_added} new shipments to Parcel across all accounts.")
            else:
                logger.info(f"Successfully added {total_added} new shipments to Parcel across all accounts.")
        else:
            logger.error("Failed to save history")
    else:
        logger.info("No new shipments to add across all accounts.")

if __name__ == "__main__":
    main()
