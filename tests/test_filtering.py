import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path with fallback to APIHelpers
try:
    from main import extract_tracking_info, _delivered_tracking_numbers
except ImportError:
    EBAY2PARCEL_ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(EBAY2PARCEL_ROOT))
    from main import extract_tracking_info, _delivered_tracking_numbers


class TestDeliveredFiltering(unittest.TestCase):
    """Test detection of delivered shipments"""

    def test_delivered_via_delivery_status_field(self):
        """Should skip tracking marked as delivered via DeliveryStatus"""
        orders = {
            'OrderArray': {
                'Order': {
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '111',
                            'ShippingCarrierUsed': 'USPS',
                            'DeliveryStatus': 'Delivered'
                        }
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 0)
        self.assertEqual(delivered_skipped, 1)
        self.assertEqual(aged_skipped, 0)

    def test_delivered_via_actual_delivery_date(self):
        """Should skip tracking with ActualDeliveryDate set"""
        orders = {
            'OrderArray': {
                'Order': {
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '222',
                            'ShippingCarrierUsed': 'UPS',
                            'ActualDeliveryDate': '2024-11-10T12:00:00.000Z'
                        }
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 0)
        self.assertEqual(delivered_skipped, 1)

    def test_delivered_via_shipment_array(self):
        """Should skip tracking marked delivered in ShipmentArray"""
        orders = {
            'OrderArray': {
                'Order': {
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '333',
                            'ShippingCarrierUsed': 'USPS'
                        }
                    },
                    'ShipmentArray': {
                        'Shipment': {
                            'ActualDeliveryDate': '2024-11-10T12:00:00.000Z',
                            'ShipmentTrackingDetails': {
                                'ShipmentTrackingNumber': '333'
                            }
                        }
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 0)
        self.assertEqual(delivered_skipped, 1)

    def test_not_delivered_no_status(self):
        """Should include tracking with no delivery indicators"""
        orders = {
            'OrderArray': {
                'Order': {
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '444',
                            'ShippingCarrierUsed': 'USPS'
                        }
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 1)
        self.assertEqual(delivered_skipped, 0)
        self.assertEqual(shipments[0]['tracking_number'], '444')


class TestAgeBasedFiltering(unittest.TestCase):
    """Test age-based filtering of old shipments"""

    def setUp(self):
        self._original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._original_env)

    def test_recent_shipment_included(self):
        """Should include shipments within age limit"""
        os.environ["MAX_SHIPMENT_AGE_DAYS"] = "45"

        recent_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace('+00:00', 'Z')

        orders = {
            'OrderArray': {
                'Order': {
                    'ShippedTime': recent_time,
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '555',
                            'ShippingCarrierUsed': 'USPS'
                        }
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 1)
        self.assertEqual(aged_skipped, 0)

    def test_old_shipment_excluded(self):
        """Should exclude shipments older than age limit"""
        os.environ["MAX_SHIPMENT_AGE_DAYS"] = "45"

        old_time = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat().replace('+00:00', 'Z')

        orders = {
            'OrderArray': {
                'Order': {
                    'ShippedTime': old_time,
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '666',
                            'ShippingCarrierUsed': 'USPS'
                        }
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 0)
        self.assertEqual(aged_skipped, 1)

    def test_age_limit_boundary(self):
        """Should exclude shipments exactly at age limit"""
        os.environ["MAX_SHIPMENT_AGE_DAYS"] = "45"

        boundary_time = (datetime.now(timezone.utc) - timedelta(days=46)).isoformat().replace('+00:00', 'Z')

        orders = {
            'OrderArray': {
                'Order': {
                    'ShippedTime': boundary_time,
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '777',
                            'ShippingCarrierUsed': 'USPS'
                        }
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 0)
        self.assertEqual(aged_skipped, 1)

    def test_no_timestamp_included(self):
        """Should include shipments with no timestamp (can't determine age)"""
        os.environ["MAX_SHIPMENT_AGE_DAYS"] = "45"

        orders = {
            'OrderArray': {
                'Order': {
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '888',
                            'ShippingCarrierUsed': 'USPS'
                        }
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 1)
        self.assertEqual(aged_skipped, 0)


class TestMixedPayloadShapes(unittest.TestCase):
    """Test handling of various payload structures from eBay API"""

    def test_multiple_orders_mixed_status(self):
        """Should handle multiple orders with mixed delivery status"""
        orders = {
            'OrderArray': {
                'Order': [
                    {
                        'ShippingDetails': {
                            'ShipmentTrackingDetails': {
                                'ShipmentTrackingNumber': '111',
                                'ShippingCarrierUsed': 'USPS',
                                'DeliveryStatus': 'Delivered'
                            }
                        }
                    },
                    {
                        'ShippingDetails': {
                            'ShipmentTrackingDetails': {
                                'ShipmentTrackingNumber': '222',
                                'ShippingCarrierUsed': 'UPS'
                            }
                        }
                    }
                ]
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 1)
        self.assertEqual(delivered_skipped, 1)
        self.assertEqual(shipments[0]['tracking_number'], '222')

    def test_tracking_details_as_list(self):
        """Should handle ShipmentTrackingDetails as list"""
        orders = {
            'OrderArray': {
                'Order': {
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': [
                            {
                                'ShipmentTrackingNumber': '111',
                                'ShippingCarrierUsed': 'USPS'
                            },
                            {
                                'ShipmentTrackingNumber': '222',
                                'ShippingCarrierUsed': 'UPS'
                            }
                        ]
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 2)
        tracking_numbers = [s['tracking_number'] for s in shipments]
        self.assertIn('111', tracking_numbers)
        self.assertIn('222', tracking_numbers)

    def test_shipment_array_as_list(self):
        """Should handle ShipmentArray.Shipment as list"""
        orders = {
            'OrderArray': {
                'Order': {
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '111',
                            'ShippingCarrierUsed': 'USPS'
                        }
                    },
                    'ShipmentArray': {
                        'Shipment': [
                            {
                                'ActualDeliveryDate': '2024-11-10T12:00:00.000Z',
                                'ShipmentTrackingDetails': {
                                    'ShipmentTrackingNumber': '111'
                                }
                            }
                        ]
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 0)
        self.assertEqual(delivered_skipped, 1)

    def test_empty_orders(self):
        """Should handle empty or missing OrderArray gracefully"""
        # Test None
        shipments, delivered, aged = extract_tracking_info(None)
        self.assertEqual(len(shipments), 0)

        # Test empty dict
        shipments, delivered, aged = extract_tracking_info({})
        self.assertEqual(len(shipments), 0)

        # Test empty OrderArray
        shipments, delivered, aged = extract_tracking_info({'OrderArray': {}})
        self.assertEqual(len(shipments), 0)

    def test_missing_optional_fields(self):
        """Should handle orders with missing optional fields"""
        orders = {
            'OrderArray': {
                'Order': {
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '999'
                            # Missing ShippingCarrierUsed
                        }
                    }
                    # Missing ShipmentArray
                    # Missing timestamps
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(orders)

        self.assertEqual(len(shipments), 1)
        self.assertEqual(shipments[0]['tracking_number'], '999')
        self.assertIsNone(shipments[0]['carrier'])


class TestDeliveredTrackingNumbersHelper(unittest.TestCase):
    """Test the _delivered_tracking_numbers helper function"""

    def test_delivered_via_shipment_status(self):
        """Should detect delivered via Shipment.Status"""
        order = {
            'ShipmentArray': {
                'Shipment': {
                    'Status': 'Delivered',
                    'ShipmentTrackingDetails': {
                        'ShipmentTrackingNumber': '111'
                    }
                }
            }
        }

        delivered = _delivered_tracking_numbers(order)
        self.assertIn('111', delivered)

    def test_delivered_via_shipment_delivery_date(self):
        """Should detect delivered via Shipment.DeliveryDate"""
        order = {
            'ShipmentArray': {
                'Shipment': {
                    'DeliveryDate': '2024-11-10T12:00:00.000Z',
                    'ShipmentTrackingDetails': {
                        'ShipmentTrackingNumber': '222'
                    }
                }
            }
        }

        delivered = _delivered_tracking_numbers(order)
        self.assertIn('222', delivered)

    def test_delivered_via_tracking_status(self):
        """Should detect delivered via tracking DeliveryStatus"""
        order = {
            'ShipmentArray': {
                'Shipment': {
                    'ShipmentTrackingDetails': {
                        'ShipmentTrackingNumber': '333',
                        'DeliveryStatus': 'delivered'
                    }
                }
            }
        }

        delivered = _delivered_tracking_numbers(order)
        self.assertIn('333', delivered)

    def test_no_delivered_shipments(self):
        """Should return empty set when no delivered shipments"""
        order = {
            'ShipmentArray': {
                'Shipment': {
                    'ShipmentTrackingDetails': {
                        'ShipmentTrackingNumber': '444'
                    }
                }
            }
        }

        delivered = _delivered_tracking_numbers(order)
        self.assertEqual(len(delivered), 0)

    def test_missing_shipment_array(self):
        """Should handle orders without ShipmentArray"""
        order = {}

        delivered = _delivered_tracking_numbers(order)
        self.assertEqual(len(delivered), 0)


if __name__ == '__main__':
    unittest.main()
