import boto3
from botocore.client import BaseClient
from botocore.config import Config
from redis import Redis
from sqlalchemy import create_engine, text

from invoiceops.config import Settings

PROBE_TIMEOUT_SECONDS = 1


def check_database(settings: Settings) -> None:
    options: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_timeout": PROBE_TIMEOUT_SECONDS,
    }
    if settings.database_url.startswith("postgresql"):
        options["connect_args"] = {"connect_timeout": PROBE_TIMEOUT_SECONDS}
    probe_engine = create_engine(settings.database_url, **options)
    try:
        with probe_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        probe_engine.dispose()


def check_redis(settings: Settings) -> None:
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
        socket_timeout=PROBE_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    finally:
        client.close()


def check_object_storage(settings: Settings) -> None:
    client: BaseClient = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        config=Config(
            connect_timeout=PROBE_TIMEOUT_SECONDS,
            read_timeout=PROBE_TIMEOUT_SECONDS,
            retries={"max_attempts": 1},
            s3={"addressing_style": "path"},
        ),
    )
    client.head_bucket(Bucket=settings.s3_bucket)


def dependency_status(settings: Settings) -> dict[str, str]:
    checks = {
        "postgresql": check_database,
        "redis": check_redis,
        "object_storage": check_object_storage,
    }
    components: dict[str, str] = {}
    for name, check in checks.items():
        try:
            check(settings)
            components[name] = "ready"
        except Exception:
            components[name] = "unavailable"
    return components
