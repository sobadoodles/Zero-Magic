"""Import a legacy export into an EMPTY database, with the new server STOPPED."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app import storage
from app.schemas import CardCreate, CardStage
from app.team import PersonInput
from app.storage import Counter

if len(sys.argv)!=2:
    raise SystemExit("Usage: python scripts/import_workspace.py workspace-export.json")
data=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if data.get("format")!="zero-magic-export-v1":
    raise SystemExit("Not a Zero Magic export.")


def records(name):
    items=data[name]
    if not isinstance(items,list):raise ValueError("Expected a list: "+name)
    result={}
    for item in items:
        ident=item.get("id")
        if type(ident) is not int or ident<1 or ident in result:raise ValueError("Invalid/duplicate IDs: "+name)
        result[ident]=item.copy()
    return result


people=records("people");cards=records("cards");comments=records("comments")
for person in people.values():
    cleaned=PersonInput.model_validate({k:person[k] for k in ("name","skills","responsibility")})
    person.clear();person.update(cleaned.model_dump())
for ident,person in people.items():person["id"]=ident
for card in cards.values():
    cleaned=CardCreate.model_validate({k:card[k] for k in ("title","goal","acceptance_criteria","out_of_scope")})
    card.update(cleaned.model_dump());card.pop("comment_count",None)
    CardStage(card["stage"])
    assignee=card.get("assignee")
    if assignee and (assignee.get("kind")!="human" or int(assignee["identifier"]) not in people):
        raise ValueError("Unknown assignee in export")
for comment in comments.values():
    if comment.get("card_id") not in cards or not isinstance(comment.get("text"),str) or not isinstance(comment.get("author"),str):
        raise ValueError("Invalid legacy comment")
    comment["user_id"]=None  # Historical labels are not authenticated identities.
    if comment.get("author_id") not in people:comment["author_id"]=None
with storage.transaction() as db:
    if storage.cards or storage.people or storage.comments or db.execute("SELECT 1 FROM users").fetchone():
        raise SystemExit("Import only into an empty database BEFORE first owner setup. Nothing imported.")
    storage.people.update(people);storage.cards.update(cards);storage.comments.update(comments)
    storage.card_ids=Counter(max(cards,default=0)+1)
    storage.person_ids=Counter(max(people,default=0)+1)
    storage.comment_ids=Counter(max(comments,default=0)+1)
print(f"Imported {len(cards)} cards, {len(people)} people, {len(comments)} comments.")
print("Start the new app and create your owner account. Existing people are retained; invite them to link logins.")
