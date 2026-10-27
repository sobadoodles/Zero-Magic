"""Project labels and immutable, explicit deletion previews. Single-worker app."""
import hashlib
import json
import time
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app import storage
from app.auth import require_user
from app.schemas import NonBlankText

router=APIRouter(prefix='/api/v1/projects', tags=['Projects'], dependencies=[Depends(require_user)])
COLORS={'indigo','blue','teal','green','amber','orange','pink','purple'}

class ProjectInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: NonBlankText=Field(max_length=80)
    color: str='indigo'

class DeleteApproval(BaseModel):
    model_config=ConfigDict(extra='forbid')
    approve: bool
    confirm_name: str=Field(max_length=80)


def validate_project(project_id):
    if project_id is not None and project_id not in storage.projects:
        raise HTTPException(404,'Project not found. Refresh and select an existing project.')


def project_for(ident):
    validate_project(str(ident));return storage.projects[str(ident)]


def can_manage(project,user):
    if not user['is_admin'] and project['owner_id']!=user['id']:
        raise HTTPException(403,'Only the project creator or workspace owner can edit or delete it.')


def check_input(payload,exclude=None):
    if payload.color not in COLORS:
        raise HTTPException(422,'Choose one of the available project colors.')
    if any(p['id']!=exclude and p['name'].casefold()==payload.name.casefold() for p in storage.projects.values()):
        raise HTTPException(409,'A project with that name already exists. Choose a distinct name.')


def summary(project):
    return {**project,'card_count':sum(c.get('project_id')==project['id'] for c in storage.cards.values()),
            'brief_count':sum(d.get('project_id')==project['id'] for d in storage.prds.values())}

@router.get('')
@storage.synchronized
def list_projects():
    return [summary(p) for p in sorted(storage.projects.values(),key=lambda p:p['name'].casefold())]

@router.post('',status_code=201)
@storage.synchronized
def create_project(payload:ProjectInput,user=Depends(require_user)):
    check_input(payload)
    if len(storage.projects)>=100:raise HTTPException(409,'This local workspace supports up to 100 projects.')
    ident=str(uuid4());now=datetime.now(timezone.utc).isoformat()
    project={'id':ident,**payload.model_dump(),'owner_id':user['id'],'created_at':now,'updated_at':now}
    storage.projects[ident]=project
    return summary(project)

@router.put('/{project_id}')
@storage.synchronized
def edit_project(project_id:UUID,payload:ProjectInput,user=Depends(require_user)):
    project=project_for(project_id);can_manage(project,user);check_input(payload,project['id'])
    project.update(payload.model_dump());project['updated_at']=datetime.now(timezone.utc).isoformat()
    return summary(project)


def deletion_snapshot(project_id):
    project=project_for(project_id)
    selected=[c for c in storage.cards.values() if c.get('project_id')==project_id]
    ids={c['id'] for c in selected}
    docs=[d for d in storage.prds.values() if d.get('project_id')==project_id]
    doc_ids={d['id'] for d in docs}
    blocked=[c['id'] for c in storage.cards.values() if c['id'] not in ids and (
        ids.intersection(c.get('depends_on',[])) or c.get('source_prd_id') in doc_ids)]
    if blocked:
        raise HTTPException(409,'Other-project or ungrouped cards reference this project. Resolve those links before deletion: '+', '.join(f'#{i}' for i in blocked))
    return {'project':deepcopy(project),'cards':deepcopy(selected),'briefs':deepcopy(docs),
            'comments':deepcopy([c for c in storage.comments.values() if c['card_id'] in ids])}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def purge_proposals(card_ids,brief_ids,project_id,keep=None):
    for key,record in list(storage.proposals.items()):
        if key==keep:continue
        data=record.get('data',{});result=record.get('result') or {}
        related=(project_id is not None and data.get('project_id')==project_id) or data.get('prd',{}).get('id') in brief_ids
        related=related or any(c.get('id') in card_ids or c.get('source_prd_id') in brief_ids for c in result.get('cards',[]))
        related=related or any(c.get('id') in card_ids for c in data.get('cards',[]))
        related=related or any(a.get('card_id') in card_ids for a in data.get('assignments',[]))
        if related:del storage.proposals[key]

@router.post('/{project_id}/deletion-preview')
@storage.synchronized
def preview_deletion(project_id:UUID,user=Depends(require_user)):
    ident=str(project_id);project=project_for(ident);can_manage(project,user)
    snap=deletion_snapshot(ident);now=time.time()
    for key,p in list(storage.proposals.items()):
        if p['expires']<now:del storage.proposals[key]
    if len(storage.proposals)>=200:raise HTTPException(429,'Too many pending previews. Try again later.')
    token=str(uuid4())
    data={'project_id':ident,'project':summary(project),
          'cards':[{'id':c['id'],'title':c['title']} for c in snap['cards']],
          'briefs':[{'id':d['id'],'title':d['title']} for d in snap['briefs']],
          'comment_count':len(snap['comments'])}
    storage.proposals[token]={'id':token,'kind':'delete_project','user_id':user['id'],'owner':'project-deletion',
        'status':'pending','expires':now+600,'data':data,'baseline':digest(snap),'result':None}
    return {'id':token,'expires_in_seconds':600,**data}

@router.post('/deletions/{token}/confirm')
@storage.synchronized
def confirm_deletion(token:UUID,payload:DeleteApproval,user=Depends(require_user)):
    record=storage.proposals.get(str(token))
    if not record or record.get('kind')!='delete_project' or record['user_id']!=user['id']:
        raise HTTPException(404,'Deletion preview not found for this account.')
    if not payload.approve or payload.confirm_name!=record['data']['project']['name']:
        raise HTTPException(422,'Type the exact project name and explicitly approve deletion.')
    if record['status']=='confirmed':return record['result']
    if record['status']!='pending':raise HTTPException(409,'This deletion preview is no longer pending.')
    if record['expires']<time.time():raise HTTPException(410,'Deletion preview expired. Review a fresh preview.')
    ident=record['data']['project_id'];can_manage(project_for(ident),user)
    snap=deletion_snapshot(ident)
    if digest(snap)!=record['baseline']:raise HTTPException(409,'This project changed. Review a fresh deletion preview.')
    ids={c['id'] for c in snap['cards']};docs={d['id'] for d in snap['briefs']}
    for key in ids:del storage.cards[key]
    for key in docs:del storage.prds[key]
    for key,c in list(storage.comments.items()):
        if c['card_id'] in ids:del storage.comments[key]
    del storage.projects[ident]
    purge_proposals(ids,docs,ident,keep=record['id'])
    result={'status':'deleted','project_id':ident,'deleted_card_ids':sorted(ids),'deleted_brief_ids':sorted(docs),
            'deleted_comments':len(snap['comments']),'message':f'Deleted project {snap["project"]["name"]}, {len(ids)} cards, {len(docs)} briefs and {len(snap["comments"])} comments.'}
    # Keep an idempotent receipt, not deleted task/document text.
    record['data']={'project_id':ident,'project':{'name':snap['project']['name']}}
    record['status']='confirmed';record['result']=result
    return result

@router.post('/deletions/{token}/cancel')
@storage.synchronized
def cancel_deletion(token:UUID,user=Depends(require_user)):
    record=storage.proposals.get(str(token))
    if not record or record.get('kind')!='delete_project' or record['user_id']!=user['id']:
        raise HTTPException(404,'Deletion preview not found for this account.')
    if record['status']=='confirmed':raise HTTPException(409,'Deletion already completed; cancellation is not an undo.')
    del storage.proposals[str(token)]
    return {'status':'cancelled'}
