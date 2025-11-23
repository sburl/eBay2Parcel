import os
import json
import requests
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from ebaysdk.trading import Connection as Trading
from ebaysdk.exception import ConnectionError

from shared_ebay.auth import ensure_valid_token, get_token_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class EbayClient:
    def __init__(self):
        # Ensure we have a valid token before starting
        if not ensure_valid_token():
            raise Exception("Failed to obtain valid eBay token")
            
        self.token = get_token_manager().get_current_token()
        self.api = Trading(
            appid=os.getenv("EBAY_APP_ID"),
            certid=os.getenv("EBAY_CLIENT_SECRET"), # Note: ebaysdk uses certid for client secret in some contexts, but for OAuth token usage, we just need the token.
            devid=os.getenv("EBAY_DEV_ID"),
            token=self.token,
            config_file=None,
            domain="api.ebay.com"
        )

    def get_recent_orders(self, days_back=30):
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
    def __init__(self):
        self.api_key = os.getenv("PARCEL_API_KEY")
        self.base_url = "https://api.parcel.app/external/add-delivery/"
        
        if not self.api_key:
            logger.warning("PARCEL_API_KEY not found in environment variables")

    def add_delivery(self, tracking_number, carrier_code, description):
        """Add a delivery to Parcel app."""
        if not self.api_key:
            logger.error("Cannot add delivery: Missing Parcel API Key")
            return False

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
                return True

            if response.status_code == 400 and error_message and "already added" in error_message.lower():
                logger.info(f"{tracking_number} already exists in Parcel; skipping")
                return True  # Treat as handled so we add to history and avoid retrying

            logger.error(
                f"Failed to add delivery. Status: {response.status_code}, "
                f"Error: {error_message or response.text}"
            )
            return False
                
        except Exception as e:
            logger.error(f"Error adding delivery to Parcel: {e}")
            return False

def load_history():
    if os.path.exists("tracking_history.json"):
        try:
            with open("tracking_history.json", "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

def save_history(history):
    with open("tracking_history.json", "w") as f:
        json.dump(history, f, indent=2)

def extract_tracking_info(orders):
    """Extract tracking numbers and carrier info from orders, skipping delivered shipments."""
    shipments = []
    delivered_skipped = 0
    
    if not orders or 'OrderArray' not in orders or not orders['OrderArray']:
        return shipments, delivered_skipped
        
    order_list = orders['OrderArray'].get('Order', [])
    if isinstance(order_list, dict):
        order_list = [order_list]
        
    for order in order_list:
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
                delivery_status = tracking.get('DeliveryStatus') or tracking.get('Status')
                delivered_time = tracking.get('ActualDeliveryDate') or tracking.get('DeliveryDate')
                delivered_flag = False
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
                    
    return shipments, delivered_skipped

def main():
    print("Starting eBay2Parcel...")
    
    # Initialize clients
    try:
        ebay = EbayClient()
        parcel = ParcelClient()
    except Exception as e:
        logger.critical(f"Initialization failed: {e}")
        return

    # Load history
    history = load_history()
    history_tracking_numbers = [item['tracking_number'] for item in history]
    
    # Fetch orders
    logger.info("Fetching recent orders from eBay...")
    orders = ebay.get_recent_orders(days_back=30)
    
    if not orders:
        logger.info("No orders found or error fetching orders.")
        return
    
    order_list = orders.get('OrderArray', {}).get('Order', [])
    if isinstance(order_list, dict):
        order_list = [order_list]
    logger.info(f"Processing {len(order_list)} orders for tracking extraction")

    # Extract shipments
    shipments, delivered_skipped = extract_tracking_info(orders)
    total_with_tracking = len(shipments) + delivered_skipped
    logger.info(
        f"Found {total_with_tracking} shipments with tracking info "
        f"(skipped {delivered_skipped} already delivered)."
    )
    
    new_shipments_count = 0
    
    for shipment in shipments:
        tracking_number = shipment['tracking_number']
        
        if tracking_number in history_tracking_numbers:
            logger.debug(f"Skipping existing tracking number: {tracking_number}")
            continue
            
        # Add to Parcel
        # Note: Parcel requires specific carrier codes. 
        # We might need a mapping, but for now we pass the carrier string from eBay
        # and hope Parcel's auto-detect or loose matching works, or use 'pholder' if unknown.
        # Ideally we should map eBay carrier names to Parcel carrier codes.
        carrier_code = shipment.get('carrier', 'pholder') 
        
        # Simple mapping for common carriers (can be expanded)
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
        
        success = parcel.add_delivery(
            tracking_number=tracking_number,
            carrier_code=carrier_code,
            description=shipment['description']
        )
        
        if success:
            history.append({
                'tracking_number': tracking_number,
                'added_at': datetime.now(timezone.utc).isoformat()
            })
            new_shipments_count += 1
            
    # Save updated history
    if new_shipments_count > 0:
        save_history(history)
        logger.info(f"Successfully added {new_shipments_count} new shipments to Parcel.")
    else:
        logger.info("No new shipments to add.")

if __name__ == "__main__":
    main()
