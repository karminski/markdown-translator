"""
Configuration management for the Markdown translator.

This module handles loading and validating configuration from environment variables
and provides access to API clients and other configuration values.
"""

import os
from typing import Dict, Any, Optional
from openai import OpenAI
from .interfaces import IConfigManager


class ConfigManager(IConfigManager):
    """
    Configuration manager that handles environment variables and API client creation.
    
    This class implements the IConfigManager interface and provides methods to:
    - Load and validate environment variables
    - Create configured OpenAI clients
    - Validate API configuration
    """
    
    # Required environment variables
    REQUIRED_ENV_VARS = {
        'TRANSLATE_API_TOKEN': 'API token for OpenRouter service'
    }
    
    # Optional environment variables with defaults
    OPTIONAL_ENV_VARS = {
        'TRANSLATE_API': 'https://openrouter.ai/api/v1',
        'TRANSLATE_MODEL': 'google/gemini-2.5-flash'
    }
    
    def __init__(self):
        """Initialize the configuration manager."""
        self._config: Dict[str, Any] = {}
        self._api_client: Optional[OpenAI] = None
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from environment variables."""
        # Load required environment variables
        for env_var, description in self.REQUIRED_ENV_VARS.items():
            value = os.getenv(env_var)
            if not value:
                raise ValueError(f"Required environment variable {env_var} is not set. {description}")
            self._config[env_var] = value
        
        # Load optional environment variables with defaults
        for env_var, default_value in self.OPTIONAL_ENV_VARS.items():
            self._config[env_var] = os.getenv(env_var, default_value)
    
    def load_environment_variables(self) -> Dict[str, str]:
        """
        Load configuration from environment variables.
        
        Returns:
            Dictionary of configuration values loaded from environment
        """
        return self._config.copy()
    
    def validate_api_config(self) -> bool:
        """
        Validate that API configuration is complete and valid.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        try:
            # Check required fields are present
            if not self._config.get('TRANSLATE_API_TOKEN'):
                return False
            
            if not self._config.get('TRANSLATE_API'):
                return False
            
            if not self._config.get('TRANSLATE_MODEL'):
                return False
            
            # Validate API URL format
            api_url = self._config['TRANSLATE_API']
            if not api_url.startswith(('http://', 'https://')):
                return False
            
            # Validate API token format
            token = self._config['TRANSLATE_API_TOKEN']
            if not token.startswith('sk-or-v1-'):
                return False
            
            # Try to create a client to validate configuration
            # Don't call _create_api_client() to avoid circular dependency
            try:
                from openai import OpenAI
                client = OpenAI(
                    api_key=token,
                    base_url=api_url
                )
                return client is not None
            except Exception:
                return False
                
        except Exception:
            return False
    
    def _create_api_client(self) -> OpenAI:
        """
        Create and configure an OpenAI client.
        
        Returns:
            Configured OpenAI client instance
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Basic validation without calling validate_api_config to avoid circular dependency
        if not self._config.get('TRANSLATE_API_TOKEN') or not self._config.get('TRANSLATE_API'):
            raise ValueError("Invalid API configuration")
        
        return OpenAI(
            api_key=self._config['TRANSLATE_API_TOKEN'],
            base_url=self._config['TRANSLATE_API']
        )
    
    def get_api_client(self) -> OpenAI:
        """
        Get a configured API client for translation services.
        
        Returns:
            Configured OpenAI client object
            
        Raises:
            ValueError: If API configuration is invalid
        """
        if self._api_client is None:
            self._api_client = self._create_api_client()
        return self._api_client
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by key.
        
        Args:
            key: Configuration key to retrieve
            default: Default value if key is not found
            
        Returns:
            Configuration value or default
        """
        return self._config.get(key, default)
    
    def get_api_base_url(self) -> str:
        """Get the API base URL."""
        return self._config['TRANSLATE_API']
    
    def get_api_token(self) -> str:
        """Get the API token."""
        return self._config['TRANSLATE_API_TOKEN']
    
    def get_model_name(self) -> str:
        """Get the model name to use for translation."""
        return self._config['TRANSLATE_MODEL']
    
    def reload_config(self) -> None:
        """Reload configuration from environment variables."""
        self._config.clear()
        self._api_client = None
        self._load_config()
