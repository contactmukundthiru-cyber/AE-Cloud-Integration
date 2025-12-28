from __future__ import annotations
import json
import time
import redis
import redis.asyncio as aioredis
from .config import settings


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def get_async_redis() -> aioredis.Redis:
    return aioredis.Redis.from_url(settings.redis_url, decode_responses=True)


def enqueue_job(job_id: str, gpu_class: str):
    client = get_redis()
    queue_name = f'queue:{gpu_class}'
    client.lpush(queue_name, job_id)


def dequeue_job(gpu_class: str, timeout: int = 5):
    client = get_redis()
    queue_name = f'queue:{gpu_class}'
    item = client.brpop(queue_name, timeout=timeout)
    if not item:
        return None
    return item[1]


def remove_job(job_id: str, gpu_class: str):
    client = get_redis()
    queue_name = f'queue:{gpu_class}'
    client.lrem(queue_name, 0, job_id)


def publish_progress(job_id: str, payload: dict):
    client = get_redis()
    payload['timestamp'] = int(time.time())
    client.publish(f'job:{job_id}', json.dumps(payload))


async def stream_job_updates(job_id: str):
    client = get_async_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(f'job:{job_id}')
    try:
        async for message in pubsub.listen():
            if message['type'] == 'message':
                yield message['data']
    finally:
        await pubsub.unsubscribe(f'job:{job_id}')
        await pubsub.close()
        await client.close()
