import os
import sys
import unittest
from pathlib import Path

EBAY2PARCEL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EBAY2PARCEL_ROOT))

from shared_ebay import config as shared_config


class ParcelConfigTests(unittest.TestCase):
    def setUp(self):
        self._original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._original_env)
        shared_config._config = {}

    def test_key_suffix_helper(self):
        self.assertEqual(shared_config._key("EBAY_APP_ID", ""), "EBAY_APP_ID")
        self.assertEqual(shared_config._key("EBAY_APP_ID", "2"), "EBAY_APP_ID_2")

    def test_suffix_specific_config(self):
        os.environ["EBAY_APP_ID"] = "app-id"
        os.environ["EBAY_CLIENT_SECRET"] = "secret"
        os.environ["EBAY_DEV_ID"] = "dev-id"
        os.environ["EBAY_APP_ID_2"] = "app-id-2"
        os.environ["EBAY_CLIENT_SECRET_2"] = "secret-2"
        os.environ["EBAY_DEV_ID_2"] = "dev-id-2"

        default_cfg = shared_config.get_config()
        suffix_cfg = shared_config.get_config("2")

        self.assertNotEqual(default_cfg.ebay_app_id, suffix_cfg.ebay_app_id)
