import os
import logging
from typing import Optional
from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseConfig:
    name: str = "bot_database.db"
    timeout: int = 30
    pragmas: dict = None
    
    def __post_init__(self):
        if self.pragmas is None:
            object.__setattr__(self, 'pragmas', {
                'journal_mode': 'wal',
                'cache_size': -64000,
                'foreign_keys': 1,
                'ignore_check_constraints': 0
            })


@dataclass(frozen=True)
class BotConfig:
    default_free_requests: int = 3
    max_requests_per_user: int = 1000
    request_timeout: int = 30


class Config:
    
    def __init__(self):
        self._load_environment_variables()
        self._validate_required_settings()
        
        self.database = DatabaseConfig()
        self.bot = BotConfig()
    
    def _load_environment_variables(self) -> None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            logging.warning("python-dotenv not installed, using system environment")
        
        self.bot_token: Optional[str] = os.getenv('BOT_TOKEN')
        self.openai_api_key: Optional[str] = os.getenv('OPENAI_API_KEY')
        
        try:
            self.admin_id: int = int(os.getenv('ADMIN_ID', '0'))
        except (TypeError, ValueError) as e:
            logging.error(f"Invalid ADMIN_ID format: {e}")
            self.admin_id = 0
    
    def _validate_required_settings(self) -> None:
        missing_vars = []
        
        if not self.bot_token:
            missing_vars.append('BOT_TOKEN')
        if not self.openai_api_key:
            missing_vars.append('OPENAI_API_KEY')
        if self.admin_id == 0:
            missing_vars.append('ADMIN_ID')
        
        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
            logging.error(error_msg)
            raise ValueError(error_msg)
    
    @property
    def is_production(self) -> bool:
        return os.getenv('ENVIRONMENT', 'development').lower() == 'production'


config = Config()
