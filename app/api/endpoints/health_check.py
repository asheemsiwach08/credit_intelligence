import logging
import time
from typing import Dict, Any

from fastapi import APIRouter, Response, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import psutil

from app.services.health_service import HealthService

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

ACTIVE_CONNECTIONS = Gauge(
    'active_connections',
    'Number of active connections'
)

SYSTEM_CPU_USAGE = Gauge(
    'system_cpu_usage_percent',
    'Current CPU usage percentage'
)

SYSTEM_MEMORY_USAGE = Gauge(
    'system_memory_usage_percent',
    'Current memory usage percentage'
)

SYSTEM_DISK_USAGE = Gauge(
    'system_disk_usage_percent',
    'Current disk usage percentage'
)

DATABASE_CONNECTION_STATUS = Gauge(
    'database_connection_status',
    'Database connection status (1=healthy, 0=unhealthy)'
)

OPENAI_CONNECTION_STATUS = Gauge(
    'openai_connection_status',
    'OpenAI API connection status (1=healthy, 0=unhealthy)'
)

# Health router
router = APIRouter(tags=["health"])

# Initialize health service
health_service = HealthService()


@router.get("/healthz")
async def liveness_check():
    """
    Basic liveness probe - checks if the application is running.
    
    Returns:
        dict: Basic health status with process information
    """
    try:
        result = await health_service.check_liveness()
        REQUEST_COUNT.labels(method='GET', endpoint='/healthz', status='200').inc()
        return result
    except Exception as e:
        logger.error(f"Liveness check failed: {e}")
        REQUEST_COUNT.labels(method='GET', endpoint='/healthz', status='500').inc()
        raise HTTPException(status_code=500, detail="Liveness check failed")


@router.get("/readyz")
async def readiness_check():
    """
    Comprehensive readiness probe - checks all dependencies.
    
    Returns:
        dict: Detailed health status of all dependencies
    """
    try:
        start_time = time.time()
        result = await health_service.check_readiness()
        
        # Update Prometheus metrics based on health check results
        _update_prometheus_metrics(result)
        
        # Record request duration
        REQUEST_DURATION.labels(method='GET', endpoint='/readyz').observe(time.time() - start_time)
        
        # Return appropriate HTTP status code based on health
        if result["status"] == "healthy":
            REQUEST_COUNT.labels(method='GET', endpoint='/readyz', status='200').inc()
            return result
        else:
            REQUEST_COUNT.labels(method='GET', endpoint='/readyz', status='503').inc()
            raise HTTPException(status_code=503, detail=result)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        REQUEST_COUNT.labels(method='GET', endpoint='/readyz', status='500').inc()
        raise HTTPException(status_code=500, detail="Readiness check failed")


@router.get("/info")
async def app_info():
    """
    Application information endpoint.
    
    Returns:
        dict: Application version, git SHA, build time, and environment info
    """
    try:
        result = await health_service.get_app_info()
        REQUEST_COUNT.labels(method='GET', endpoint='/info', status='200').inc()
        return result
    except Exception as e:
        logger.error(f"App info check failed: {e}")
        REQUEST_COUNT.labels(method='GET', endpoint='/info', status='500').inc()
        raise HTTPException(status_code=500, detail="App info retrieval failed")


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """
    Prometheus metrics endpoint.
    
    Returns:
        str: Prometheus formatted metrics
    """
    try:
        # Update system metrics before generating output
        _update_system_metrics()
        
        REQUEST_COUNT.labels(method='GET', endpoint='/metrics', status='200').inc()
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )
    except Exception as e:
        logger.error(f"Metrics generation failed: {e}")
        REQUEST_COUNT.labels(method='GET', endpoint='/metrics', status='500').inc()
        raise HTTPException(status_code=500, detail="Metrics generation failed")


def _update_prometheus_metrics(health_result: Dict[str, Any]) -> None:
    """Update Prometheus metrics based on health check results."""
    try:
        checks = health_result.get("checks", {})
        
        # Update database connection status
        db_check = checks.get("database", {})
        if db_check.get("status") == "healthy":
            DATABASE_CONNECTION_STATUS.set(1)
        elif db_check.get("status") == "skipped":
            DATABASE_CONNECTION_STATUS.set(-1)  # -1 for not configured
        else:
            DATABASE_CONNECTION_STATUS.set(0)
        
        # Update OpenAI connection status
        openai_check = checks.get("openai", {})
        if openai_check.get("status") == "healthy":
            OPENAI_CONNECTION_STATUS.set(1)
        else:
            OPENAI_CONNECTION_STATUS.set(0)
        
        # Update system resource metrics
        system_check = checks.get("system_resources", {})
        if system_check:
            SYSTEM_CPU_USAGE.set(system_check.get("cpu_percent", 0))
            SYSTEM_MEMORY_USAGE.set(system_check.get("memory_percent", 0))
            SYSTEM_DISK_USAGE.set(system_check.get("disk_percent", 0))
            
    except Exception as e:
        logger.error(f"Failed to update Prometheus metrics: {e}")


def _update_system_metrics() -> None:
    """Update system-level Prometheus metrics."""
    try:
        # Update CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)
        SYSTEM_CPU_USAGE.set(cpu_percent)
        
        # Update memory usage
        memory = psutil.virtual_memory()
        SYSTEM_MEMORY_USAGE.set(memory.percent)
        
        # Update disk usage
        disk = psutil.disk_usage('/')
        SYSTEM_DISK_USAGE.set(disk.percent)
        
    except Exception as e:
        logger.error(f"Failed to update system metrics: {e}")


# Middleware function to track requests (can be used with FastAPI middleware)
def track_request_metrics(method: str, endpoint: str, status_code: int, duration: float):
    """Track request metrics for Prometheus."""
    REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=str(status_code)).inc()
    REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
