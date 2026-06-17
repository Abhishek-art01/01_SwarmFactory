import ssl

import redis.asyncio as aioredis

from core.config import Settings


def test_redis_connection_kwargs_use_string_cert_reqs_for_redis_py():
    settings = Settings(
        AZURE_OPENAI_ENDPOINT="https://test.openai.azure.com/",
        AZURE_OPENAI_API_KEY="test-key",
        REDIS_URL="rediss://localhost:6380/0",
        REDIS_SSL_CERT_REQS="required",
        API_KEY="test-api-key",
        SECRET_KEY="test-secret-key",
    )

    assert settings.redis_ssl_cert_reqs == ssl.CERT_REQUIRED
    assert settings.celery_redis_ssl_options == {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    assert settings.redis_connection_kwargs == {"ssl_cert_reqs": "required"}

    client = aioredis.from_url(
        settings.REDIS_URL,
        **settings.redis_connection_kwargs,
    )
    connection = client.connection_pool.make_connection()

    assert connection.ssl_context.cert_reqs == ssl.CERT_REQUIRED
