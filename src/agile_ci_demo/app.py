from typing import Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Agile CI Demo", version="0.1.0")


class Item(BaseModel):
    id: int
    title: str
    done: bool = False


# naive in-memory "database" – fine for a teaching/demo app
_db: Dict[int, Item] = {}


@app.get("/health")
def health() -> dict:
    """Simple health check endpoint used by tests and monitoring."""
    return {"status": "ok"}


@app.post("/items", status_code=201)
def create_item(item: Item) -> Item:
    """Create a new todo item.

    Returns 409 if an item with the same ID already exists.
    """
    if item.id in _db:
        raise HTTPException(status_code=409, detail="Item with that ID already exists")

    _db[item.id] = item
    return item


@app.get("/items/{item_id}")
def get_item(item_id: int) -> Item:
    """Fetch a single item by ID."""
    if item_id not in _db:
        raise HTTPException(status_code=404, detail="Not found")
    return _db[item_id]


@app.patch("/items/{item_id}/done")
def mark_done(item_id: int) -> Item:
    """Mark an item as done."""
    if item_id not in _db:
        raise HTTPException(status_code=404, detail="Not found")

    item = _db[item_id]
    item.done = True
    _db[item_id] = item
    return item


# Optional: helper for tests to reset state (not exposed as an endpoint)
def reset_db() -> None:
    _db.clear()
