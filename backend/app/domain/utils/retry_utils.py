import asyncio
import logging
from typing import TypeVar, Callable, Any
from functools import wraps
import random

logger = logging.getLogger(__name__)

T = TypeVar('T')

class RateLimitError(Exception):
    """Raised when API returns rate limit error (429)"""
    pass

async def retry_with_exponential_backoff(
    func: Callable[..., Any],
    *args,
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    **kwargs
) -> Any:
    """
    Retry a coroutine function with exponential backoff for rate limit errors.
    
    Args:
        func: Async function to retry
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        *args: Arguments to pass to func
        **kwargs: Keyword arguments to pass to func
    
    Returns:
        Result from func
        
    Raises:
        The original exception if all retries are exhausted
    """
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            logger.debug(f"Attempt {attempt + 1}/{max_retries} to call {func.__name__}")
            result = await func(*args, **kwargs)
            if attempt > 0:
                logger.info(f"Successfully called {func.__name__} after {attempt} retries")
            return result
        except Exception as e:
            last_exception = e
            error_str = str(e)
            
            # Check if it's a rate limit error (429) or queue exceeded
            is_rate_limit = (
                "429" in error_str or 
                "queue_exceeded" in error_str or
                "high traffic" in error_str or
                "too_many_requests" in error_str
            )
            
            if not is_rate_limit:
                # Not a rate limit error, raise immediately
                logger.error(f"Non-rate-limit error in {func.__name__}: {error_str}")
                raise
            
            if attempt == max_retries - 1:
                # Last attempt, raise the error
                logger.error(f"All {max_retries} retries exhausted for {func.__name__}")
                raise
            
            # Calculate delay with jitter
            jitter = random.uniform(0, 0.1 * delay)
            wait_time = min(delay + jitter, max_delay)
            
            logger.warning(
                f"Rate limit hit in {func.__name__} (attempt {attempt + 1}/{max_retries}). "
                f"Retrying in {wait_time:.2f} seconds... Error: {error_str[:100]}"
            )
            
            await asyncio.sleep(wait_time)
            delay = min(delay * exponential_base, max_delay)
    
    # Should not reach here, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError(f"Failed to call {func.__name__} after {max_retries} retries")

def retry_on_rate_limit(
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0
):
    """
    Decorator to retry async functions with exponential backoff on rate limit errors.
    
    Usage:
        @retry_on_rate_limit(max_retries=5, initial_delay=1.0)
        async def call_llm():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_with_exponential_backoff(
                func,
                *args,
                max_retries=max_retries,
                initial_delay=initial_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                **kwargs
            )
        return wrapper
    return decorator
