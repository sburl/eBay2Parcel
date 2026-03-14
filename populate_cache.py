#!/usr/bin/env python3
"""
Populate tracking_history.json with all tracking numbers from eBay
without adding them to Parcel. This prevents re-adding items you've deleted.
"""

import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from main import EbayClient, load_history, save_history, _account_suffixes
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

def extract_all_tracking_numbers(orders):
    """Extract ALL tracking numbers from orders, regardless of delivery status."""
    tracking_numbers = set()

    if not orders or 'OrderArray' not in orders or not orders['OrderArray']:
        return tracking_numbers

    order_list = orders['OrderArray'].get('Order', [])
    if isinstance(order_list, dict):
        order_list = [order_list]

    for order in order_list:
        # Check ShippingDetails
        if 'ShippingDetails' in order:
            shipping_details = order['ShippingDetails']
            tracking_details = shipping_details.get('ShipmentTrackingDetails') or []

            # Also check transactions
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
                if tracking_number:
                    tracking_numbers.add(tracking_number)

        # Check ShipmentArray
        shipments = order.get('ShipmentArray', {}).get('Shipment', [])
        if isinstance(shipments, dict):
            shipments = [shipments]

        for shipment in shipments:
            tracking_details = shipment.get('ShipmentTrackingDetails') or []
            if isinstance(tracking_details, dict):
                tracking_details = [tracking_details]

            for tracking in tracking_details:
                tracking_number = tracking.get('ShipmentTrackingNumber')
                if tracking_number:
                    tracking_numbers.add(tracking_number)

    return tracking_numbers

def main():
    print("Populating tracking_history.json with all eBay tracking numbers...")

    history = load_history()
    existing_tracking_numbers = {item['tracking_number'] for item in history}

    suffixes = _account_suffixes()
    if not suffixes:
        logger.critical("No EBAY_APP_ID configured in environment")
        return

    all_tracking_numbers = set()

    for suffix in suffixes:
        label = f"default" if not suffix else f"account {suffix}"
        logger.info(f"[{label}] Fetching all orders from eBay...")

        try:
            ebay = EbayClient(suffix=suffix)
        except Exception as e:
            logger.error(f"[{label}] Failed to initialize: {e}")
            continue

        orders = ebay.get_recent_orders(days_back=90)

        if not orders:
            logger.info(f"[{label}] No orders found")
            continue

        tracking_numbers = extract_all_tracking_numbers(orders)
        logger.info(f"[{label}] Found {len(tracking_numbers)} tracking numbers")
        all_tracking_numbers.update(tracking_numbers)

    # Add new tracking numbers to history
    new_count = 0
    current_time = datetime.now(timezone.utc).isoformat()

    for tracking_number in all_tracking_numbers:
        if tracking_number not in existing_tracking_numbers:
            history.append({
                'tracking_number': tracking_number,
                'added_at': current_time
            })
            new_count += 1

    if new_count > 0:
        save_history(history)
        logger.info(f"Added {new_count} new tracking numbers to cache")
        logger.info(f"Total tracking numbers in cache: {len(history)}")
    else:
        logger.info("All tracking numbers already in cache")

    print("\nDone! All eBay tracking numbers are now in tracking_history.json")
    print("This prevents them from being re-added to Parcel if you delete them.")

if __name__ == "__main__":
    main()
