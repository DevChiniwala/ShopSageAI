import logging
from typing import Dict, Any
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

from shopsage.auth.tenant_store import TenantStore

logger = logging.getLogger("shopsage.auth.api_key")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
tenant_store = TenantStore()

async def verify_api_key(
    api_key: str = Security(api_key_header)
) -> Dict[str, Any]:
    """
    Dependency to verify the API key and return the associated tenant.
    
    Args:
        api_key (str): The API key from the request header.
        
    Returns:
        Dict[str, Any]: The tenant record.
        
    Raises:
        HTTPException: If the API key is missing or invalid.
    """
    if not api_key:
        logger.warning("Missing API key in request.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )
        
    tenant = tenant_store.get_tenant_by_key(api_key)
    if not tenant:
        logger.warning(f"Invalid API key provided: {api_key[:4]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
        
    # Increment usage count for the tenant
    tenant_store.increment_usage(tenant["id"])
    
    return tenant
