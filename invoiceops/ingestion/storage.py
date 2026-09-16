from typing import Protocol

import boto3
from botocore.client import BaseClient

from invoiceops.config import Settings


class ObjectStore(Protocol):
    def put(self, key: str, body: bytes, content_type: str) -> None: ...

    def delete(self, key: str) -> None: ...


class S3ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.server_side_encryption = settings.s3_server_side_encryption
        self.client: BaseClient = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except self.client.exceptions.ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, body: bytes, content_type: str) -> None:
        request: dict[str, object] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
        }
        if self.server_side_encryption:
            request["ServerSideEncryption"] = self.server_side_encryption
        self.client.put_object(**request)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)
