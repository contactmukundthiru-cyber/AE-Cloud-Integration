from __future__ import annotations
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from .config import settings


def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
        use_ssl=settings.s3_use_ssl,
        config=Config(signature_version='s3v4')
    )


def ensure_bucket():
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


def generate_presigned_put(key: str) -> tuple[str, dict]:
    client = get_s3_client()
    params = {
        'Bucket': settings.s3_bucket,
        'Key': key,
        'ServerSideEncryption': settings.s3_server_side_encryption
    }
    url = client.generate_presigned_url('put_object', Params=params, ExpiresIn=settings.s3_presign_expiry_seconds)
    return url, {'x-amz-server-side-encryption': settings.s3_server_side_encryption}


def generate_presigned_get(key: str) -> str:
    client = get_s3_client()
    params = {'Bucket': settings.s3_bucket, 'Key': key}
    return client.generate_presigned_url('get_object', Params=params, ExpiresIn=settings.s3_presign_expiry_seconds)


def upload_file(file_path: str, key: str):
    client = get_s3_client()
    extra = {'ServerSideEncryption': settings.s3_server_side_encryption}
    client.upload_file(file_path, settings.s3_bucket, key, ExtraArgs=extra)


def download_file(key: str, dest_path: str):
    client = get_s3_client()
    client.download_file(settings.s3_bucket, key, dest_path)


def object_exists(key: str) -> bool:
    client = get_s3_client()
    try:
        client.head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError:
        return False


def get_object_size(key: str) -> int:
    client = get_s3_client()
    response = client.head_object(Bucket=settings.s3_bucket, Key=key)
    return int(response.get('ContentLength', 0))
