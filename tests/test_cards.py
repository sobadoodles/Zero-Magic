from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_create_card():
    response = client.post(
        "/api/v1/cards",
        json={
            "title": "First card",
            "goal": "Learn FastAPI",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == 1
    assert data["title"] == "First card"
    assert data["goal"] == "Learn FastAPI"
    assert data["stage"] == "Spec"
    assert data["assignee"] is None
    assert data["acceptance_criteria"] == []
    assert data["out_of_scope"] == ""


def test_list_cards():
    client.post(
        "/api/v1/cards",
        json={
            "title": "First card",
            "goal": "Learn FastAPI",
        },
    )

    response = client.get("/api/v1/cards")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "First card"


def test_get_card():
    client.post(
        "/api/v1/cards",
        json={
            "title": "First card",
            "goal": "Learn FastAPI",
        },
    )

    response = client.get("/api/v1/cards/1")

    assert response.status_code == 200
    assert response.json()["id"] == 1


def test_get_missing_card_returns_404():
    response = client.get("/api/v1/cards/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Card not found"


def test_update_card():
    client.post(
        "/api/v1/cards",
        json={
            "title": "Old title",
            "goal": "Old goal",
        },
    )

    response = client.patch(
        "/api/v1/cards/1",
        json={
            "title": "New title",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "New title"
    assert data["goal"] == "Old goal"


def test_delete_card():
    client.post(
        "/api/v1/cards",
        json={
            "title": "Delete me",
            "goal": "Test delete",
        },
    )

    delete_response = client.delete("/api/v1/cards/1")
    assert delete_response.status_code == 204

    get_response = client.get("/api/v1/cards/1")
    assert get_response.status_code == 404