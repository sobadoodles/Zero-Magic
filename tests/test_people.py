from itertools import count

import pytest
from fastapi.testclient import TestClient

from app import team
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_people():
    team.people.clear()
    team.person_ids = count(start=1)
    yield
    team.people.clear()
    team.person_ids = count(start=1)


def make_person():
    response = client.post("/api/v1/people", json={
        "name": "  Sara  ", "skills": ["  Vue  ", "Testing"],
        "responsibility": "Frontend",
    })
    assert response.status_code == 201
    return response.json()


def make_card():
    response = client.post("/api/v1/cards", json={"title":"Task", "goal":"Test assignment"})
    assert response.status_code == 201
    return response.json()


def test_create_and_list_people():
    assert client.get("/api/v1/people").json() == []
    person = make_person()
    assert person["name"] == "Sara"
    assert person["skills"] == ["Vue", "Testing"]
    assert client.get("/api/v1/people").json() == [person]


def test_edit_person():
    person = make_person()
    response = client.put(f"/api/v1/people/{person['id']}", json={
        "name":"Sara", "skills":["Vue", "TypeScript"], "responsibility":"UI",
    })
    assert response.status_code == 200
    assert response.json()["skills"] == ["Vue", "TypeScript"]


def test_blank_person_rejected():
    assert client.post("/api/v1/people",json={"name":"   "}).status_code == 422
    assert client.get("/api/v1/people").json() == []


def test_assign_and_unassign_person():
    person, card = make_person(), make_card()
    path = f"/api/v1/cards/{card['id']}/assignee"
    response = client.patch(path,json={"person_id":person["id"]})
    assert response.status_code == 200
    expected = {"kind":"human", "identifier":str(person["id"])}
    assert response.json()["assignee"] == expected
    assert client.get(f"/api/v1/cards/{card['id']}").json()["assignee"] == expected
    assert client.patch(path,json={"person_id":None}).json()["assignee"] is None
    assert client.get(f"/api/v1/cards/{card['id']}").json()["assignee"] is None


def test_unknown_person_does_not_change_assignment():
    person, card = make_person(), make_card()
    path = f"/api/v1/cards/{card['id']}/assignee"
    client.patch(path,json={"person_id":person["id"]})
    assert client.patch(path,json={"person_id":999}).status_code == 404
    assert client.get(f"/api/v1/cards/{card['id']}").json()["assignee"]["identifier"] == str(person["id"])


def test_assign_missing_card():
    assert client.patch("/api/v1/cards/999/assignee",json={"person_id":None}).status_code == 404


def test_missing_assignment_key_rejected():
    card=make_card()
    assert client.patch(f"/api/v1/cards/{card['id']}/assignee",json={}).status_code == 422


def test_update_missing_person():
    assert client.put("/api/v1/people/999",json={"name":"Sara"}).status_code == 404
