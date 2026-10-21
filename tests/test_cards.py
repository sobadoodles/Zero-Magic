from fastapi.testclient import TestClient

from app.main import app
import pytest

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

def test_update_rejects_null_title():
    created = client.post(
        "/api/v1/cards",
        json={
            "title": "Keep this title",
            "goal": "Test update validation",
        },
    )
    card_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/cards/{card_id}",
        json={"title": None},
    )

    assert response.status_code == 422

    saved_card = client.get(f"/api/v1/cards/{card_id}")
    assert saved_card.json()["title"] == "Keep this title"

def test_move_card_from_spec_to_ready():
    created = client.post(
        "/api/v1/cards",
        json={"title": "First task", "goal": "Test stage transitions"},
    )
    card_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/cards/{card_id}/stage",
        json={"stage": "Ready"},
    )

    assert response.status_code == 200
    assert response.json()["stage"] == "Ready"

    saved = client.get(f"/api/v1/cards/{card_id}")
    assert saved.json()["stage"] == "Ready"


def test_cannot_move_card_from_spec_to_done():
    created = client.post(
        "/api/v1/cards",
        json={"title": "First task", "goal": "Test illegal transitions"},
    )
    card_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/cards/{card_id}/stage",
        json={"stage": "Done"},
    )

    assert response.status_code == 409

    saved = client.get(f"/api/v1/cards/{card_id}")
    assert saved.json()["stage"] == "Spec"

@pytest.mark.parametrize(
    "next_stage",
    ["Building", "Checks", "Validation", "Done"],
)
def test_cannot_skip_stages_from_spec(next_stage):
    created = client.post(
        "/api/v1/cards",
        json={"title": "Task", "goal": "Check stage rules"},
    )
    card_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/cards/{card_id}/stage",
        json={"stage": next_stage},
    )

    assert response.status_code == 409

    saved = client.get(f"/api/v1/cards/{card_id}")
    assert saved.json()["stage"] == "Spec"


def test_card_can_complete_full_workflow():
    created = client.post(
        "/api/v1/cards",
        json={"title": "Task", "goal": "Complete the workflow"},
    )
    card_id = created.json()["id"]

    for stage in ["Ready", "Building", "Checks", "Validation", "Done"]:
        response = client.patch(
            f"/api/v1/cards/{card_id}/stage",
            json={"stage": stage},
        )

        assert response.status_code == 200
        assert response.json()["stage"] == stage


def test_unknown_stage_returns_422():
    created = client.post(
        "/api/v1/cards",
        json={"title": "Task", "goal": "Reject unknown stages"},
    )
    card_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/cards/{card_id}/stage",
        json={"stage": "Banana"},
    )

    assert response.status_code == 422


def test_change_stage_of_missing_card_returns_404():
    response = client.patch(
        "/api/v1/cards/999/stage",
        json={"stage": "Ready"},
    )

    assert response.status_code == 404

@pytest.mark.parametrize(
    "path",
    [
        ["Ready", "Building", "Checks"],
        ["Ready", "Building", "Checks", "Validation"],
    ],
)
def test_card_can_be_sent_back_to_building(path):
    created = client.post(
        "/api/v1/cards",
        json={"title": "Task", "goal": "Test returning work"},
    )
    card_id = created.json()["id"]

    for stage in path:
        response = client.patch(
            f"/api/v1/cards/{card_id}/stage",
            json={"stage": stage},
        )
        assert response.status_code == 200

    response = client.patch(
        f"/api/v1/cards/{card_id}/stage",
        json={"stage": "Building"},
    )

    assert response.status_code == 200

    saved = client.get(f"/api/v1/cards/{card_id}")
    assert saved.json()["stage"] == "Building"


def test_done_card_cannot_return_to_building():
    created = client.post(
        "/api/v1/cards",
        json={"title": "Task", "goal": "Test terminal stage"},
    )
    card_id = created.json()["id"]

    for stage in ["Ready", "Building", "Checks", "Validation", "Done"]:
        response = client.patch(
            f"/api/v1/cards/{card_id}/stage",
            json={"stage": stage},
        )
        assert response.status_code == 200

    response = client.patch(
        f"/api/v1/cards/{card_id}/stage",
        json={"stage": "Building"},
    )

    assert response.status_code == 409

    saved = client.get(f"/api/v1/cards/{card_id}")
    assert saved.json()["stage"] == "Done"