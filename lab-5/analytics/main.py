import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import aio_pika
from fastapi import FastAPI, HTTPException

RABBITMQ_URL = os.environ["RABBITMQ_URL"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("analytics")

stores = {}
stats = {"events_received": 0}


def new_store(store_id):
    return {
        "store_id": store_id,
        "purchases_applied": 0,
        "returns_applied": 0,
        "redeems_applied": 0,
        "rejected": 0,
        "points_accrued": 0,
        "points_returned": 0,
        "points_redeemed": 0,
    }


def handle(event):
    stats["events_received"] += 1
    store = stores.setdefault(event["store_id"], new_store(event["store_id"]))
    if event["status"] == "rejected":
        store["rejected"] += 1
    elif event["type"] == "purchase":
        store["purchases_applied"] += 1
        store["points_accrued"] += event["points_delta"]
    elif event["type"] == "return":
        store["returns_applied"] += 1
        store["points_returned"] += abs(event["points_delta"])
    elif event["type"] == "redeem":
        store["redeems_applied"] += 1
        store["points_redeemed"] += abs(event["points_delta"])
    log.info("%s %s %s %s", event["operation_id"], event["store_id"], event["type"], event["status"])


async def consume(queue):
    async with queue.iterator() as messages:
        async for message in messages:
            async with message.process(requeue=True):
                handle(json.loads(message.body.decode("utf-8")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    events = await channel.declare_exchange(
        "loyalty.events", aio_pika.ExchangeType.FANOUT, durable=True
    )
    queue = await channel.declare_queue(
        "analytics.events", durable=True, arguments={"x-queue-type": "quorum"}
    )
    await queue.bind(events, routing_key="")
    task = asyncio.create_task(consume(queue))
    yield
    task.cancel()
    await connection.close()


app = FastAPI(lifespan=lifespan)


@app.get("/stores")
async def get_stores():
    return list(stores.values())


@app.get("/stores/{store_id}")
async def get_store(store_id: str):
    if store_id not in stores:
        raise HTTPException(status_code=404, detail="Нет событий по магазину")
    return stores[store_id]


@app.get("/stats")
async def get_stats():
    return stats
