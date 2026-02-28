"""Authentication and authorization."""
from typing import Optional
from datetime import datetime, timedelta
import secrets
from enum import Enum


class UserRole(str, Enum):
    """User roles."""
    ADMIN = "admin"
    POWER_USER = "power_user"
    USER = "user"
    GUEST = "guest"


class RateLimit:
    """Rate limiting tracker."""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: dict = {}
    
    def is_allowed(self, user_id: str) -> bool:
        """Check if request is allowed."""
        now = datetime.utcnow()
        
        if user_id not in self.requests:
            self.requests[user_id] = []
        
        cutoff = now - timedelta(seconds=self.window_seconds)
        self.requests[user_id] = [
            req_time for req_time in self.requests[user_id]
            if req_time > cutoff
        ]
        
        if len(self.requests[user_id]) < self.max_requests:
            self.requests[user_id].append(now)
            return True
        
        return False


class APIKeyManager:
    """Manage API keys for authentication."""
    
    def __init__(self):
        self.keys = {}
        self._init_default()
    
    def _init_default(self):
        """Initialize default keys."""
        self.keys["dev_key_admin"] = {"role": UserRole.ADMIN, "active": True}
        self.keys["dev_key_user"] = {"role": UserRole.USER, "active": True}
    
    def validate_key(self, key: str) -> Optional[UserRole]:
        """Validate API key."""
        if key in self.keys and self.keys[key]["active"]:
            return self.keys[key]["role"]
        return None


class Authenticator:
    """Handle authentication and authorization."""
    
    def __init__(self):
        self.api_key_manager = APIKeyManager()
        self.rate_limiter = RateLimit()
    
    def authenticate_request(self, api_key: str) -> Optional[dict]:
        """Authenticate request."""
        role = self.api_key_manager.validate_key(api_key)
        if role:
            return {"authenticated": True, "role": role}
        return None
    
    def check_rate_limit(self, user_id: str) -> bool:
        """Check rate limit."""
        return self.rate_limiter.is_allowed(user_id)
