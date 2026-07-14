"""RQ worker entrypoint. Run: `python -m app.workers.rq_worker`."""

from redis import Redis
from rq import Queue, Worker

from app.config import settings


def main():
    conn = Redis.from_url(settings.redis_url)
    Worker([Queue("ingestion", connection=conn)], connection=conn).work()


if __name__ == "__main__":
    main()