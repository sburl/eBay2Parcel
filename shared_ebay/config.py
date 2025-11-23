"""
Configuration settings for shared eBay client
"""
import os
import logging
from typing import Optional, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when configuration is invalid or incomplete"""
    pass


def _key(base: str, suffix: str) -> str:
    return f"{base}_{suffix}" if suffix else base


class Config:
    """eBay Configuration (supports multiple accounts via numeric suffix)"""
    
    def __init__(self, suffix: str = ""):
        self.suffix = suffix
        env = lambda k, default=None: os.getenv(_key(k, suffix), default)

        # Required eBay credentials
        self.ebay_app_id = env('EBAY_APP_ID')
        self.ebay_client_secret = env('EBAY_CLIENT_SECRET')
        self.ebay_dev_id = env('EBAY_DEV_ID')
        
        # User token (can be empty on first run, will be obtained via OAuth)
        self.ebay_user_token = env('EBAY_USER_TOKEN', '')
        self.ebay_refresh_token = env('EBAY_REFRESH_TOKEN', '')
        
        # API Endpoints
        self.ebay_browse_api_url = "https://api.ebay.com/buy/browse/v1"
        
        # Shipping Configuration
        self.shipping_zip_code = env('SHIPPING_ZIP_CODE', '00000')
        
        # Sales Tax Configuration
        try:
            self.sales_tax_rate = float(env('SALES_TAX_RATE', '0.0'))
        except ValueError:
            self.sales_tax_rate = 0.0
            
    def validate(self):
        """Validate required configuration"""
        if not self.ebay_app_id:
            raise ConfigurationError(_key("EBAY_APP_ID", self.suffix) + " not set")
        if not self.ebay_client_secret:
            raise ConfigurationError(_key("EBAY_CLIENT_SECRET", self.suffix) + " not set")


# Global configuration instances keyed by suffix
_config: Dict[str, Config] = {}

def get_config(suffix: str = "") -> Config:
    """Get the global configuration instance"""
    global _config
    if suffix not in _config:
        _config[suffix] = Config(suffix)
    return _config[suffix]
