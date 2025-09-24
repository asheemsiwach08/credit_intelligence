import logging
import os
import subprocess
import time
from datetime import datetime
from typing import Dict, Any, Optional

import psutil
import psycopg2
from openai import OpenAI

from app.config.settings import settings


class HealthService:
    """Service for checking application health and dependencies."""
    
    def __init__(self):
        host = settings.POSTGRES_HOST
        port = settings.POSTGRES_PORT
        dbname = settings.POSTGRES_DB
        user = settings.POSTGRES_USER
        password = settings.POSTGRES_PASSWORD
        dsn = f"host={host} port={port} dbname={dbname} user={user} password={password}"
        self.dsn = dsn
        self.openai_api_key = settings.OPENAI_API_KEY
        self.s3_bucket = settings.S3_BUCKET
        self.logger = logging.getLogger(__name__)
    
    async def check_liveness(self) -> Dict[str, Any]:
        """Basic liveness check - just confirms the process is running."""
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "process_id": os.getpid(),
            "uptime_seconds": time.time() - psutil.Process().create_time()
        }
    
    async def check_readiness(self) -> Dict[str, Any]:
        """Comprehensive readiness check including all dependencies."""
        checks = {
            "database": await self._check_database(),
            "openai": await self._check_openai(),
            "aws_s3": await self._check_aws_s3(),
            "system_resources": await self._check_system_resources()
        }
        
        # Determine overall status
        all_healthy = all(check["status"] == "healthy" for check in checks.values())
        overall_status = "healthy" if all_healthy else "unhealthy"
        
        return {
            "status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "checks": checks
        }
    
    async def get_app_info(self) -> Dict[str, Any]:
        """Get application version, git SHA, and build information."""
        return {
            "app_name": "Credit Intelligence API",
            "version": "1.0.0",
            "git_sha": self._get_git_sha(),
            "build_time": self._get_build_time(),
            "python_version": f"{psutil.sys.version_info.major}.{psutil.sys.version_info.minor}.{psutil.sys.version_info.micro}",
            "environment": os.getenv("ENV", "development"),
            "timestamp": datetime.now().isoformat()
        }
    
    async def _check_database(self) -> Dict[str, Any]:
        """Check PostgreSQL database connectivity."""
        try:
            # Only check if database is configured (using pg_dsn)
            
            if not self.dsn:
                return {
                    "status": "skipped",
                    "message": "Database not configured",
                    "response_time_ms": 0
                }
            
            start_time = time.time()
            conn = psycopg2.connect(self.dsn, connect_timeout=5)
            
            # Simple query to test connectivity
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            
            response_time = (time.time() - start_time) * 1000
            
            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2),
                "message": "Database connection successful"
            }
            
        except Exception as e:
            self.logger.error(f"Database health check failed: {e}")
            return {
                "status": "unhealthy",
                "message": f"Database connection failed: {str(e)}",
                "response_time_ms": 0
            }
    
    async def _check_openai(self) -> Dict[str, Any]:
        """Check OpenAI API connectivity."""
        try:
            if not self.openai_api_key:
                return {
                    "status": "unhealthy",
                    "message": "OpenAI API key not configured",
                    "response_time_ms": 0
                }
            
            start_time = time.time()
            client = OpenAI(api_key=self.openai_api_key)
            
            # Simple API call to test connectivity
            models = client.models.list()
            response_time = (time.time() - start_time) * 1000
            
            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2),
                "message": "OpenAI API connection successful",
                "models_available": len(models.data) if hasattr(models, 'data') else 0
            }
            
        except Exception as e:
            self.logger.error(f"OpenAI health check failed: {e}")
            return {
                "status": "unhealthy",
                "message": f"OpenAI API connection failed: {str(e)}",
                "response_time_ms": 0
            }
    
    async def _check_aws_s3(self) -> Dict[str, Any]:
        """Check AWS S3 connectivity."""
        try:
            import boto3
            from botocore.exceptions import ClientError, NoCredentialsError
            
            # Only check if S3 is configured
            if not self.s3_bucket:
                return {
                    "status": "skipped",
                    "message": "S3 not configured",
                    "response_time_ms": 0
                }
            
            start_time = time.time()
            s3_client = boto3.client('s3')
            
            # Try to list objects in the bucket (with limit to avoid large responses)
            s3_client.list_objects_v2(Bucket=self.s3_bucket, MaxKeys=1)
            response_time = (time.time() - start_time) * 1000
            
            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2),
                "message": "S3 connection successful",
                "bucket": self.s3_bucket
            }
            
        except NoCredentialsError:
            return {
                "status": "unhealthy",
                "message": "AWS credentials not configured",
                "response_time_ms": 0
            }
        except ClientError as e:
            error_code = e.response['Error']['Code']
            return {
                "status": "unhealthy",
                "message": f"S3 connection failed: {error_code}",
                "response_time_ms": 0
            }
        except Exception as e:
            self.logger.error(f"S3 health check failed: {e}")
            return {
                "status": "unhealthy",
                "message": f"S3 connection failed: {str(e)}",
                "response_time_ms": 0
            }
    
    async def _check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage."""
        try:
            # Get memory usage
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Define thresholds
            memory_threshold = 90  # 90% memory usage
            disk_threshold = 90    # 90% disk usage
            cpu_threshold = 95     # 95% CPU usage
            
            # Check if any resource is above threshold
            memory_healthy = memory.percent < memory_threshold
            disk_healthy = disk.percent < disk_threshold
            cpu_healthy = cpu_percent < cpu_threshold
            
            overall_healthy = all([memory_healthy, disk_healthy, cpu_healthy])
            
            warnings = []
            if not memory_healthy:
                warnings.append(f"High memory usage: {memory.percent:.1f}%")
            if not disk_healthy:
                warnings.append(f"High disk usage: {disk.percent:.1f}%")
            if not cpu_healthy:
                warnings.append(f"High CPU usage: {cpu_percent:.1f}%")
            
            return {
                "status": "healthy" if overall_healthy else "warning",
                "memory_percent": round(memory.percent, 1),
                "disk_percent": round(disk.percent, 1),
                "cpu_percent": round(cpu_percent, 1),
                "warnings": warnings,
                "message": "System resources within normal range" if overall_healthy else "Resource usage high"
            }
            
        except Exception as e:
            self.logger.error(f"System resource check failed: {e}")
            return {
                "status": "unhealthy",
                "message": f"System resource check failed: {str(e)}"
            }
    
    def _get_git_sha(self) -> Optional[str]:
        """Get the current git SHA if available."""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return None
    
    def _get_build_time(self) -> Optional[str]:
        """Get build time from environment variable or file modification time."""
        # Check for build time environment variable first
        build_time = os.getenv('BUILD_TIME')
        if build_time:
            return build_time
        
        # Fallback to main.py modification time
        try:
            main_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'main.py')
            if os.path.exists(main_file):
                mtime = os.path.getmtime(main_file)
                return datetime.fromtimestamp(mtime).isoformat()
        except Exception:
            pass
        
        return None
