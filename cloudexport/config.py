from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List


class Settings(BaseSettings):
    app_name: str = 'CloudExport'
    environment: str = 'development'
    api_base_url: str = 'http://localhost:8000'
    dashboard_url: str = 'http://localhost:8000/dashboard'

    database_url: str = 'postgresql+psycopg2://cloudexport:cloudexport@localhost:5432/cloudexport'
    redis_url: str = 'redis://localhost:6379/0'

    s3_endpoint_url: str | None = None
    s3_bucket: str = 'cloudexport'
    s3_region: str = 'us-east-1'
    s3_access_key_id: str = 'minioadmin'
    s3_secret_access_key: str = 'minioadmin'
    s3_use_ssl: bool = False
    s3_presign_expiry_seconds: int = 3600
    s3_server_side_encryption: str = 'AES256'

    jwt_secret: str = 'change-me'
    jwt_algorithm: str = 'HS256'
    access_token_expire_minutes: int = 60 * 24 * 7

    bootstrap_admin_email: str = 'admin@cloudexport.io'
    bootstrap_api_key: str = 'cloudexport-dev-key'

    min_job_cost_usd: float = 1.00
    storage_rate_per_gb_hour: float = 0.001
    transfer_rate_per_gb: float = 0.05
    upload_mbps: float = 50.0

    gpu_classes: List[str] = ['rtx4090', 'a100']
    gpu_rate_per_minute: dict = Field(default_factory=lambda: {'rtx4090': 0.5, 'a100': 2.0})
    gpu_speed_factor: dict = Field(default_factory=lambda: {'rtx4090': 1.0, 'a100': 1.6})

    max_retry_attempts: int = 3
    render_timeout_minutes: int = 120
    retention_days: int = 7

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = 'CloudExport <noreply@cloudexport.io>'

    lemon_webhook_secret: str | None = None
    lemon_variant_credits: str = '{}'
    lemon_auto_create_users: bool = False

    class Config:
        env_file = '.env'


settings = Settings()
