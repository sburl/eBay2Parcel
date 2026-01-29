import unittest
from unittest.mock import MagicMock, patch
import json
import os
from main import extract_tracking_info, ParcelClient, EbayClient

class TesteBay2Parcel(unittest.TestCase):

    def test_extract_tracking_info(self):
        # Mock eBay order response
        mock_orders = {
            'OrderArray': {
                'Order': [
                    {
                        'ShippingDetails': {
                            'ShipmentTrackingDetails': {
                                'ShipmentTrackingNumber': '1234567890',
                                'ShippingCarrierUsed': 'USPS'
                            }
                        },
                        'TransactionArray': {
                            'Transaction': {
                                'Item': {'Title': 'Test Item 1'}
                            }
                        }
                    },
                    {
                        'ShippingDetails': {
                            'ShipmentTrackingDetails': [
                                {
                                    'ShipmentTrackingNumber': '0987654321',
                                    'ShippingCarrierUsed': 'UPS'
                                }
                            ]
                        },
                        'TransactionArray': {
                            'Transaction': {
                                'Item': {'Title': 'Test Item 2'}
                            }
                        }
                    }
                ]
            }
        }
        
        shipments, delivered_skipped, aged_skipped = extract_tracking_info(mock_orders)
        self.assertEqual(len(shipments), 2)
        self.assertEqual(delivered_skipped, 0)
        self.assertEqual(aged_skipped, 0)
        self.assertEqual(shipments[0]['tracking_number'], '1234567890')
        self.assertEqual(shipments[0]['carrier'], 'USPS')
        self.assertEqual(shipments[1]['tracking_number'], '0987654321')
        self.assertEqual(shipments[1]['carrier'], 'UPS')

    def test_extract_tracking_info_skips_delivered(self):
        mock_orders = {
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
        shipments, delivered_skipped, aged_skipped = extract_tracking_info(mock_orders)
        self.assertEqual(len(shipments), 0)
        self.assertEqual(delivered_skipped, 1)
        self.assertEqual(aged_skipped, 0)

    def test_extract_tracking_info_skips_delivery_marked_in_shipment_array(self):
        mock_orders = {
            'OrderArray': {
                'Order': {
                    'ShippingDetails': {
                        'ShipmentTrackingDetails': {
                            'ShipmentTrackingNumber': '222',
                            'ShippingCarrierUsed': 'UPS'
                        }
                    },
                    'ShipmentArray': {
                        'Shipment': {
                            'ActualDeliveryDate': '2024-11-10T12:00:00.000Z',
                            'ShipmentTrackingDetails': {
                                'ShipmentTrackingNumber': '222'
                            }
                        }
                    }
                }
            }
        }

        shipments, delivered_skipped, aged_skipped = extract_tracking_info(mock_orders)
        self.assertEqual(len(shipments), 0)
        self.assertEqual(delivered_skipped, 1)
        self.assertEqual(aged_skipped, 0)

    @patch('main.requests.post')
    def test_parcel_client_add_delivery_success(self, mock_post):
        # Mock environment variable
        with patch.dict(os.environ, {'PARCEL_API_KEY': 'test_key'}):
            client = ParcelClient()

            # Mock successful response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            success, rate_limited = client.add_delivery('123', 'usps', 'Test')
            self.assertTrue(success)
            self.assertFalse(rate_limited)

            # Verify API call
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(kwargs['json']['tracking_number'], '123')
            self.assertEqual(kwargs['headers']['api-key'], 'test_key')

    @patch('main.requests.post')
    def test_parcel_client_add_delivery_already_exists(self, mock_post):
        with patch.dict(os.environ, {'PARCEL_API_KEY': 'test_key'}):
            client = ParcelClient()

            # Mock 400 response with "already added" error
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {'error_message': 'Delivery already added'}
            mock_post.return_value = mock_response

            success, rate_limited = client.add_delivery('123', 'usps', 'Test')
            self.assertTrue(success)  # Should treat as success
            self.assertFalse(rate_limited)

    @patch('main.requests.post')
    def test_parcel_client_add_delivery_unsupported_carrier(self, mock_post):
        with patch.dict(os.environ, {'PARCEL_API_KEY': 'test_key'}):
            client = ParcelClient()

            # Mock 400 response with unsupported carrier error
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {'error_message': 'Unsupported carrier'}
            mock_post.return_value = mock_response

            success, rate_limited = client.add_delivery('123', 'invalid', 'Test')
            self.assertFalse(success)
            self.assertFalse(rate_limited)

    @patch('main.requests.post')
    def test_parcel_client_add_delivery_rate_limited(self, mock_post):
        with patch.dict(os.environ, {'PARCEL_API_KEY': 'test_key'}):
            client = ParcelClient()

            # Mock 429 rate limit response
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.json.return_value = {'error_message': 'Rate limit exceeded'}
            mock_response.text = 'Rate limit exceeded'
            mock_post.return_value = mock_response

            success, rate_limited = client.add_delivery('123', 'usps', 'Test')
            self.assertFalse(success)
            self.assertTrue(rate_limited)

    @patch('main.requests.post')
    def test_parcel_client_add_delivery_server_error(self, mock_post):
        with patch.dict(os.environ, {'PARCEL_API_KEY': 'test_key'}):
            client = ParcelClient()

            # Mock 500 server error response
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.json.side_effect = Exception("No JSON")
            mock_response.text = 'Internal Server Error'
            mock_post.return_value = mock_response

            success, rate_limited = client.add_delivery('123', 'usps', 'Test')
            self.assertFalse(success)
            self.assertFalse(rate_limited)

    @patch('main.requests.post')
    def test_parcel_client_add_delivery_missing_api_key(self, mock_post):
        with patch.dict(os.environ, {}, clear=True):
            client = ParcelClient()

            success, rate_limited = client.add_delivery('123', 'usps', 'Test')
            self.assertFalse(success)
            self.assertFalse(rate_limited)
            mock_post.assert_not_called()

if __name__ == '__main__':
    unittest.main()
