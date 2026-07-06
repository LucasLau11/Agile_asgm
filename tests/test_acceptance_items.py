from __future__ import annotations

from typing import Dict

import pytest
from fastapi.testclient import TestClient
from hypothesis import given as hypothesis_given
from hypothesis import strategies as st
from pytest_bdd import given as bdd_given, parsers, scenarios, then as bdd_then, when as bdd_when

from agile_ci_demo.app import app, reset_db

# --- Test client fixture -----------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    """
    Shared FastAPI test client.

    We reset the in-memory DB before every test so tests stay independent.
    """
    reset_db()
    return TestClient(app)


# --- 1. Basic acceptance tests (docstring Given/When/Then) -------------------


def test_health(client: TestClient) -> None:
    """
    Acceptance test: API health check

    Given the API is running
    When I GET /health
    Then I receive 200 and {"status": "ok"}
    """
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_and_get_item(client: TestClient) -> None:
    """
    Acceptance test: Add a todo item

    Given the API is running
    When I POST /items with a new item
    Then I receive 201 and the item is persisted
    And I can GET /items/{id} to retrieve it
    """
    item = {"id": 1, "title": "Read agile guide"}

    # When: create the item
    r = client.post("/items", json=item)
    assert r.status_code == 201
    created = r.json()
    assert created["id"] == 1
    assert created["title"] == "Read agile guide"
    assert created["done"] is False

    # Then: get it back
    r2 = client.get("/items/1")
    assert r2.status_code == 200
    fetched = r2.json()
    assert fetched == created


def test_conflict_on_duplicate(client: TestClient) -> None:
    """
    Acceptance test: Reject duplicate IDs

    Given an item with ID 2 exists
    When I POST another item with ID 2
    Then I receive 409 Conflict
    """
    item = {"id": 2, "title": "Duplicate"}

    # First create succeeds
    r1 = client.post("/items", json=item)
    assert r1.status_code == 201

    # Second create fails
    r2 = client.post("/items", json=item)
    assert r2.status_code == 409


def test_mark_done(client: TestClient) -> None:
    """
    Acceptance test: Mark an item as done

    Given an item with ID 3 exists
    When I PATCH /items/3/done
    Then the item is marked as done
    """
    item = {"id": 3, "title": "Finish demo"}

    client.post("/items", json=item)

    r = client.patch("/items/3/done")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 3
    assert body["done"] is True


# --- 2. Negative / edge-case tests ------------------------------------------


def test_get_missing_item_returns_404(client: TestClient) -> None:
    """
    Negative test: Getting a non-existent item

    Given no items exist
    When I GET /items/999
    Then I receive 404 Not Found
    """
    r = client.get("/items/999")
    assert r.status_code == 404
    assert r.json()["detail"] == "Not found"


def test_mark_done_missing_item_returns_404(client: TestClient) -> None:
    """
    Negative test: Marking a non-existent item as done

    Given no items exist
    When I PATCH /items/123/done
    Then I receive 404 Not Found
    """
    r = client.patch("/items/123/done")
    assert r.status_code == 404
    assert r.json()["detail"] == "Not found"


def test_mark_done_twice_keeps_item_done(client: TestClient) -> None:
    """
    Negative-ish test: Marking an item done twice

    Given an item with ID 5 exists
    When I PATCH /items/5/done twice
    Then the item remains done and no error occurs
    """
    item = {"id": 5, "title": "Double done"}
    client.post("/items", json=item)

    r1 = client.patch("/items/5/done")
    assert r1.status_code == 200
    assert r1.json()["done"] is True

    r2 = client.patch("/items/5/done")
    assert r2.status_code == 200
    assert r2.json()["done"] is True


# --- 3. Parametrized tests (multiple examples) -------------------------------


@pytest.mark.parametrize(
    "item_id,title",
    [
        (10, "First task"),
        (11, "Second task"),
        (12, "Third task"),
    ],
)
def test_create_multiple_items(client: TestClient, item_id: int, title: str) -> None:
    """
    Parametrized acceptance test: multiple examples of the same rule

    Rule:
      When I create an item with a unique ID
      Then it is persisted and can be retrieved.
    """
    r = client.post("/items", json={"id": item_id, "title": title})
    assert r.status_code == 201

    r2 = client.get(f"/items/{item_id}")
    assert r2.status_code == 200
    data = r2.json()
    assert data["id"] == item_id
    assert data["title"] == title
    assert data["done"] is False


# --- 4. Property-based test (many random inputs) -----------------------------


@hypothesis_given(
    item_id=st.integers(min_value=1, max_value=100_000),
    title=st.text(min_size=1, max_size=50),
)
def test_create_item_with_many_random_inputs(item_id: int, title: str) -> None:
    """
    Property-based test:

    For many random (item_id, title) pairs:
      - Creating the item returns either 201 (first time)
        or 409 (if the ID already exists).
    """
    # Note: using a fresh client here; we don't reset DB between examples.
    client = TestClient(app)

    response = client.post("/items", json={"id": item_id, "title": title})

    assert response.status_code in (201, 409)


# --- 5. BDD-style tests with pytest-bdd --------------------------------------
# Feature file: tests/features/items.feature
#
# This demonstrates how to connect Gherkin feature files to step functions.


# Load all scenarios from the feature file.
# The path is relative to THIS test file. We assume:
#   tests/
#     test_acceptance_items.py
#     features/
#       items.feature
scenarios("features/items.feature")


# Shared context for BDD steps
class Context:
    def __init__(self) -> None:
        self.last_response = None  # type: ignore[assignment]


@pytest.fixture
def context() -> Context:
    return Context()


@bdd_given("the API is running", target_fixture="api_is_running")
def api_is_running(client: TestClient, context: Context) -> Dict[str, object]:
    """
    BDD Given step: ensure we have a client and clean DB.

    The 'target_fixture' argument makes this step available as a fixture
    named 'api_is_running', which we can then request in When/Then steps.
    """
    # client fixture already reset the DB.
    context.last_response = None
    return {"client": client}


@bdd_when(parsers.parse('I create an item with id {item_id:d} and title "{title}"'))
def create_item_step(
    api_is_running: Dict[str, object],
    context: Context,
    item_id: int,
    title: str,
) -> None:
    """
    BDD When step: create a new item.
    """
    client: TestClient = api_is_running["client"]  # type: ignore[assignment]
    response = client.post("/items", json={"id": item_id, "title": title})
    context.last_response = response
    assert response.status_code == 201


@bdd_then(parsers.parse('the item with id {item_id:d} exists with title "{title}" and not done'))
def item_exists_step(
    api_is_running: Dict[str, object],
    context: Context,
    item_id: int,
    title: str,
) -> None:
    """
    BDD Then step: verify the item exists and is not done.
    """
    client: TestClient = api_is_running["client"]  # type: ignore[assignment]

    # Optional: also ensure the last response looked correct
    assert context.last_response is not None
    created = context.last_response.json()
    assert created["id"] == item_id
    assert created["title"] == title
    assert created["done"] is False

    # And we can GET it again
    r = client.get(f"/items/{item_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == item_id
    assert data["title"] == title
    assert data["done"] is False
