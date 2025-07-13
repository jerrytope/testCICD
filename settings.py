import os
from typing import Optional

class Settings:
    """Application settings."""
    
    def __init__(self):
        # Azure OpenAI settings
        self.azure_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")
        self.azure_api_base: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.azure_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        
        # Azure Storage settings
        self.azure_storage_connection_string: str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
        
        # Default values for testing
        if not self.azure_api_key:
            self.azure_api_key = "test_key"
        if not self.azure_api_base:
            self.azure_api_base = "https://test.openai.azure.com/"
        if not self.azure_storage_connection_string:
            self.azure_storage_connection_string = "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=test;EndpointSuffix=core.windows.net" 