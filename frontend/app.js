"use strict";
const $ = selector => document.querySelector(selector);
const STAGES = ["Spec", "Ready", "Building", "Checks", "Validation", "Done"];
const MOVES = {Spec:["Ready"], Ready:["Building"], Building:["Checks"], Checks:["Validation","Building"], Validation:["Done","Building"], Done:[]};
const state = {cards:[], people:[], peopleReady:false, selected:null, opener:null, detailsVersion:0, loadVersion:0, history:[], chatBusy:false, personEdit:null, chatId:crypto.randomUUID(), proposal:null, lastCreated:[], threadId:null, threadVersion:0, threadBusy:false, authEpoch:0, user:null, authMode:"login", inviteToken:null};

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function button(text, className = "button-quiet") {
  const el = node("button", className, text); el.type = "button"; return el;
}
function notify(target, text = "", error = false) {
  const el = typeof target === "string" ? $(target) : target;
  el.textContent = text; el.classList.toggle("error", error);
}
async function api(path, options = {}) {
  const epoch=state.authEpoch;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), path.includes("/assistant/chat") ? 135000 : 20000);
  try {
    const response = await fetch(path, {cache:"no-store", credentials:"same-origin", ...options, signal:controller.signal});
    const raw = response.status === 204 ? "" : await response.text();
    let data;
    try { data = raw ? JSON.parse(raw) : null; } catch { data = null; }
    if (!response.ok) {
      if (response.status === 401 && !path.startsWith("/api/v1/auth/")) expireSession();
      let detail = data?.detail;
      if (Array.isArray(detail)) detail = detail.map(e => `${e.loc?.slice(1).join(".") || "Input"}: ${e.msg}`).join("; ");
      if (typeof detail !== "string") detail = "The server could not complete the request.";
      throw new Error(`HTTP ${response.status}: ${detail}`);
    }
    if(epoch!==state.authEpoch)throw new Error("Your session changed. Please try again.");
    if (raw && data === null) throw new Error("The server returned an unexpected response. Check your API route.");
    return data;
  } catch(error) {
    if (error.name === "AbortError") throw new Error("The request timed out. Please try again.");
    if (error instanceof TypeError) throw new Error("Cannot reach the server. Check that FastAPI is running.");
    throw error;
  } finally { clearTimeout(timer); }
}
const json = (method, body) => ({method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
async function action(control, target, work) {
  control.disabled = true; notify(target);
  try { await work(); } catch(error) { notify(target, error.message, true); }
  finally { control.disabled = false; }
}
function showDialog(dialog, opener) {
  if (opener) dialog._opener = opener;
  if (!dialog.open) dialog.showModal();
}
function closeDialog(dialog) {
  if (dialog.querySelector(".inline-editor [type=submit]:disabled")) return;
  if (dialog.querySelector(".inline-editor") && !confirm("Discard the unsaved field edit?")) return;
  if (dialog.id === "details") { state.detailsVersion++; state.selected = null; }
  if (dialog.id === "thread-dialog") {state.threadId=null; state.threadVersion++;}
  dialog.close();
  const opener = dialog._opener;
  if (opener?.isConnected) opener.focus();
  else $("#new-card").focus();
}
for (const dialog of document.querySelectorAll("dialog")) {
  dialog.querySelectorAll("[data-close]").forEach(el => el.addEventListener("click", () => closeDialog(dialog)));
  dialog.addEventListener("cancel", event => {event.preventDefault(); closeDialog(dialog);});
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeDialog(dialog);
  });
}
function initials(name) { return name.split(/\s+/).slice(0,2).map(s => s[0]).join("").toUpperCase(); }
function assigneeName(card) {
  const a = card.assignee;
  if (!a) return "Unassigned";
  const person = state.people.find(p => String(p.id) === String(a.identifier));
  return person?.name || `Assigned: ${a.identifier}`;
}
function upsert(card) {
  const i = state.cards.findIndex(c => c.id === card.id);
  if (i < 0) state.cards.push(card); else state.cards[i] = {...state.cards[i],...card};
  renderBoard();
}
async function loadBoard() {
  const version = ++state.loadVersion;
  const cards = await api("/api/v1/cards");
  if (version !== state.loadVersion) return;
  state.cards = cards; renderBoard();
}
async function loadPeople() {
  state.people = await api("/api/v1/people"); state.peopleReady = true;
  if(state.user){
    const self=state.people.find(p=>p.id===state.user.person_id);
    if(self){state.user.name=self.name;$("#account-open").replaceChildren(node("span","avatar",initials(self.name)),node("span","account-name",self.name));
      $("#account-description").textContent=`${self.name} · @${state.user.username}${state.user.is_admin ? " · Workspace owner" : ""}`;}
  }
  renderPeople(); renderPersonFilter(); renderBoard();
  const selected = state.cards.find(c => c.id === state.selected);
  if (selected) renderAssignee(selected);
}
function renderPersonFilter() {
  const select = $("#person-filter"); const value = select.value;
  select.replaceChildren(new Option("Everyone", ""), new Option("Unassigned", "unassigned"));
  for (const p of state.people) select.add(new Option(p.name, String(p.id)));
  if ([...select.options].some(o => o.value === value)) select.value = value;
  $("#people-count").textContent = state.people.length;
}
function renderBoard() {
  const board = $("#board"); board.replaceChildren();
  const filter = $("#person-filter").value;
  const visible = state.cards.filter(c => !filter || (filter === "unassigned" ? !c.assignee : String(c.assignee?.identifier) === filter));
  $("#board-total").textContent = `${visible.length}${filter ? ` of ${state.cards.length}` : ""} ${state.cards.length === 1 ? "card" : "cards"}`;
  for (const stage of STAGES) {
    const column = node("section", "board-column"); column.dataset.stage = stage;
    const matches = visible.filter(c => c.stage === stage);
    const heading = node("div", "column-header");
    const dot = node("span", "stage-dot"); dot.setAttribute("aria-hidden","true");
    heading.append(dot, node("h3", "", stage), node("span", "column-count", matches.length));
    column.append(heading);
    if (!matches.length) column.append(node("p", "column-empty", "No cards"));
    for (const card of matches) {
      const article = node("article", "board-card"); article.dataset.cardId = card.id;
      article.tabIndex = 0; article.setAttribute("aria-label", `Open card ${card.id}: ${card.title}`);
      const open = () => openCard(card.id, article).catch(e => notify("#message",e.message,true));
      article.addEventListener("click", event => {if (!event.target.closest("button,input,textarea,form,select")) open();});
      article.addEventListener("keydown", event => {if (event.target === article && ["Enter"," "].includes(event.key)) {event.preventDefault(); open();}});
      article.append(node("p", "card-ref", `#${card.id}`));
      const title = button(card.title,"editable card-title"); title.setAttribute("aria-label",`Edit title: ${card.title}`);
      title.addEventListener("click", () => editField(title, card, "title", false));
      const goal = button(card.goal,"editable card-goal"); goal.setAttribute("aria-label",`Edit goal for ${card.title}`);
      goal.addEventListener("click", () => editField(goal, card, "goal", true));
      article.append(title,goal);
      const bottom = node("div","card-bottom");
      const assign = button("", "member-chip"); const name = assigneeName(card);
      assign.setAttribute("aria-label",`Assign ${card.title}. Current: ${name}`);
      if (card.assignee) bottom.title = name;
      if (card.assignee) assign.append(node("span","avatar",initials(name)));
      assign.append(node("span","",name));
      assign.addEventListener("click", async () => {
        try {await openCard(card.id,assign); $("#assignee-select").focus();} catch(e) {notify("#message",e.message,true);}
      });
      const discussion = button("", "comment-trigger");
      discussion.dataset.commentCount = card.id;
      setCommentLabel(discussion, card);
      discussion.addEventListener("click", () => openThread(card.id,discussion).catch(e=>notify("#message",e.message,true)));
      bottom.append(assign,discussion); article.append(bottom);
      column.append(article);
    }
    if (stage === "Spec") {
      const add = button("+ Add a card", "add-in-column"); add.addEventListener("click", () => openCreate(add)); column.append(add);
    }
    board.append(column);
  }
}

function editField(display, card, field, multiline) {
  const scope = display.closest("dialog") || $("#board");
  const active = scope.querySelector(".inline-editor");
  if (active) { active.querySelector("input,textarea").focus(); return; }
  const boardControls = display.closest("#board")
    ? [$("#new-card"), $("#team-open"), $("#person-filter"), $("#refresh")]
    : [];
  boardControls.forEach(el => { el.disabled = true; });
  const form = node("form", "inline-editor");
  const input = document.createElement(multiline ? "textarea" : "input");
  input.value = field === "acceptance_criteria" ? (card[field] || []).join("\n") : card[field] || "";
  input.setAttribute("aria-label",`Edit ${field.replaceAll("_"," ")}`);
  if (multiline) input.rows = field === "acceptance_criteria" ? 5 : 3;
  if (["title","goal"].includes(field)) input.required = true;
  const save = button("Save","button-primary"); save.type = "submit";
  const cancel = button("Cancel");
  const actions = node("div","editor-actions"); actions.append(save,cancel);
  const error = node("p","editor-error"); error.setAttribute("role","alert");
  form.append(input,actions,error); display.hidden = true; display.after(form); input.focus();
  const discard = () => {form.remove(); display.hidden = false; boardControls.forEach(el => { el.disabled = false; }); if (display.isConnected) display.focus();};
  cancel.addEventListener("click",discard);
  input.addEventListener("keydown",event => {
    if (event.key === "Escape") {event.preventDefault(); event.stopPropagation(); discard();}
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {event.preventDefault(); form.requestSubmit();}
  });
  form.addEventListener("submit",async event => {
    event.preventDefault();
    let value = input.value.trim();
    if (["title","goal"].includes(field) && !value) {error.textContent = "This field cannot be blank."; return;}
    if (field === "acceptance_criteria") value = value.split("\n").map(s => s.trim()).filter(Boolean);
    save.disabled = cancel.disabled = input.disabled = true;
    try {
      const updated = await api(`/api/v1/cards/${card.id}`,json("PATCH",{[field]:value}));
      state.loadVersion++; upsert(updated);
      if (state.selected === card.id && $("#details").open) renderFields(updated);
      notify(state.selected === card.id ? "#detail-message" : "#message","Saved.");
    } catch(e) {error.textContent = e.message;}
    finally {
      save.disabled = cancel.disabled = input.disabled = false;
      if (!error.textContent) discard();
    }
  });
}
function renderFields(card) {
  const fields = $("#card-fields"); fields.replaceChildren();
  for (const [field,label,multiline,placeholder] of [
    ["title","Title",false,"Add a title"],
    ["goal","Goal",true,"Add a goal"],
    ["acceptance_criteria","Acceptance criteria · one per line",true,"Click to add acceptance criteria"],
    ["out_of_scope","Out of scope",true,"Click to add scope notes"],
  ]) {
    const block = node("div","field-block"); block.dataset.field = field;
    const raw = field === "acceptance_criteria" ? (card[field] || []).map(s => `• ${s}`).join("\n") : card[field];
    const display = button(raw || placeholder,"editable" + (!raw ? " placeholder-text" : ""));
    display.setAttribute("aria-label",`Edit ${label.split(" ·")[0].toLowerCase()}`);
    display.addEventListener("click",() => editField(display,card,field,multiline));
    block.append(node("span","field-label",label),display); fields.append(block);
  }
}
function renderStage(card) {
  const select = $("#stage-select"); select.replaceChildren(new Option(card.stage,card.stage));
  for (const stage of MOVES[card.stage] || []) select.add(new Option(`Move to ${stage}`,stage));
  select.value = card.stage; select.disabled = !(MOVES[card.stage] || []).length;
  $("#stage-hint").textContent = select.disabled ? "Done is final in this workflow." : "Stage and assignment changes save immediately. Only allowed next stages are shown.";
}
function renderAssignee(card) {
  const select = $("#assignee-select"); select.replaceChildren(new Option("Unassigned",""));
  for (const p of state.people) select.add(new Option(p.name,String(p.id)));
  if (card.assignee) {
    const value = String(card.assignee.identifier);
    if (![...select.options].some(o => o.value === value)) select.add(new Option(assigneeName(card),value));
    select.value = value;
  }
  select.disabled = !state.peopleReady;
  if (!state.peopleReady) select.title = "Install the team API to enable assignment.";
}
async function openCard(id,opener) {
  if ($("#board .inline-editor")) throw new Error("Save or cancel the field edit before opening a card.");
  const version = ++state.detailsVersion;
  const card = await api(`/api/v1/cards/${id}`);
  if (version !== state.detailsVersion) return;
  state.selected = id; notify("#detail-message");
  $("#card-reference").textContent = `Card #${id}`;
  renderFields(card); renderStage(card); renderAssignee(card);
  showDialog($("#details"),opener);
}
$("#stage-select").addEventListener("change",async event => {
  const select = event.target; const id = state.selected; const stage = select.value;
  await action(select,"#detail-message",async () => {
    const updated = await api(`/api/v1/cards/${id}/stage`,json("PATCH",{stage}));
    if (updated.stage !== stage) throw new Error("The server did not confirm this stage change.");
    state.loadVersion++; upsert(updated);
    if (state.selected === id) notify("#detail-message",`Moved to ${updated.stage}.`);
  });
  if (state.selected === id) renderStage(state.cards.find(c => c.id === id));
});
$("#assignee-select").addEventListener("change",async event => {
  const select = event.target; const id = state.selected; const personId = select.value ? Number(select.value) : null;
  await action(select,"#detail-message",async () => {
    const updated = await api(`/api/v1/cards/${id}/assignee`,json("PATCH",{person_id:personId}));
    state.loadVersion++; upsert(updated);
    if (state.selected === id) notify("#detail-message","Assignment saved.");
  });
  if (state.selected === id) renderAssignee(state.cards.find(c => c.id === id));
});
function openCreate(opener) {notify($("#card-form .feedback")); showDialog($("#create-dialog"),opener);}
$("#new-card").addEventListener("click",event => openCreate(event.currentTarget));
$("#card-form").addEventListener("submit",event => {
  event.preventDefault(); const form = event.currentTarget;
  action(form.querySelector("[type=submit]"),form.querySelector(".feedback"),async () => {
    const fields = new FormData(form);
    const created = await api("/api/v1/cards",json("POST",{title:fields.get("title"),goal:fields.get("goal")}));
    state.loadVersion++; upsert(created); form.reset(); $("#person-filter").value=""; renderBoard();
    closeDialog($("#create-dialog")); await openCard(created.id,$("#new-card"));
  });
});
$("#person-filter").addEventListener("change",renderBoard);
$("#refresh").addEventListener("click",event => action(event.currentTarget,"#message",async () => {
  if ($("#board .inline-editor")) throw new Error("Save or cancel the field edit before refreshing.");
  await loadBoard();
}));
function renderPeople() {
  const list = $("#people-list"); list.replaceChildren();
  if (!state.people.length) list.append(node("p","muted","No people yet. Add your first teammate below."));
  for (const p of state.people) {
    const row = node("div","person-row"); const copy = node("div","person-copy");
    copy.append(node("strong","",p.name),node("p","",p.skills.join(" · ") || "No skills listed"));
    if (p.responsibility) copy.append(node("p","",p.responsibility));
    const edit = button("Edit"); edit.setAttribute("aria-label",`Edit ${p.name}`);
    edit.addEventListener("click",() => {
      $("#person-form").hidden=false; state.personEdit=p.id; $("#person-name").value=p.name; $("#person-skills").value=p.skills.join(", "); $("#person-role").value=p.responsibility;
      $("#person-form-heading").textContent="Edit person"; $("#person-form [type=submit]").textContent="Save person"; $("#cancel-person-edit").hidden=false; $("#person-name").focus();
    });
    const controls=node("div","person-actions");
    if (state.user?.is_admin || state.user?.person_id===p.id) controls.append(edit);
    if (p.has_login) copy.append(node("span","login-label","Account connected"));
    else if (state.user?.is_admin) {
      const invite=button("Invite"); invite.setAttribute("aria-label",`Invite ${p.name}`);
      invite.addEventListener("click",()=>action(invite,"#team-message",async()=>{
        const result=await api("/api/v1/auth/invitations",json("POST",{person_id:p.id}));
        const url=new URL(location.href);url.search="";url.hash="invite="+result.token;
        $("#invite-url").value=url.href;notify("#invite-message");showDialog($("#invite-dialog"),invite);
      }));controls.append(invite);
    }
    row.append(node("span","avatar",initials(p.name)),copy,controls); list.append(row);
  }
}
function resetPersonForm() {
  $("#person-form").reset(); $("#person-form").hidden=!state.user?.is_admin; state.personEdit=null; $("#person-form-heading").textContent="Add a person"; $("#person-form [type=submit]").textContent="Add person"; $("#cancel-person-edit").hidden=true;
}
$("#cancel-person-edit").addEventListener("click",resetPersonForm);
$("#team-open").addEventListener("click",event => {
  showDialog($("#team-dialog"),event.currentTarget);
  loadPeople().catch(e => notify("#team-message",`People API unavailable. Install app/team.py and its router first. ${e.message}`,true));
});
$("#person-form").addEventListener("submit",event => {
  event.preventDefault(); const form = event.currentTarget;
  action(form.querySelector("[type=submit]"),"#team-message",async () => {
    const fields = new FormData(form);
    const body = {name:fields.get("name"),skills:fields.get("skills").split(",").map(s=>s.trim()).filter(Boolean),responsibility:fields.get("responsibility")};
    await api(state.personEdit ? `/api/v1/people/${state.personEdit}` : "/api/v1/people",json(state.personEdit ? "PUT" : "POST",body));
    resetPersonForm(); await loadPeople(); notify("#team-message","Person saved.");
  });
});


// Compact card badges open a conversation; there are no board-sized composers.
function setCommentLabel(control, card) {
  control.replaceChildren();
  const icon=node("span","comment-icon");icon.setAttribute("aria-hidden","true");
  control.append(icon,node("span","",String(card.comment_count || 0)));
  control.title="Open comments";
  control.setAttribute("aria-label",`Open discussion for ${card.title}: ${card.comment_count || 0} comments`);
}
function updateCommentCount(id, count) {
  const card = state.cards.find(c=>c.id===id);
  if (card) card.comment_count=count;
  for (const control of document.querySelectorAll(`[data-comment-count="${id}"]`)) {
    if (card) setCommentLabel(control,card);
  }
}
async function postReply(id,text) {
  if (!state.user) throw new Error("Sign in to comment.");
  if (!text.trim()) throw new Error("A comment cannot be blank.");
  await api(`/api/v1/cards/${id}/comments`,json("POST",{text:text.trim()}));
}
function renderThread(items,scrollToEnd=false) {
  const container=$("#thread-messages");
  const atEnd=container.scrollHeight-container.scrollTop-container.clientHeight<48;
  // Avoid announcing/replacing the same messages on every poll.
  const signature=JSON.stringify(items);
  if (container.dataset.signature===signature) return;
  container.dataset.signature=signature;container.replaceChildren();
  if (!items.length) container.append(node("p","muted","No replies yet. Start the discussion."));
  for (const item of items) {
    const row=node("article","thread-message");
    const avatar=node("span","avatar",initials(item.author));
    const copy=node("div","thread-copy");
    const header=node("div","thread-message-header");header.append(node("strong","",item.author));
    if(!item.user_id)header.append(node("span","legacy-label","Legacy comment"));
    if (item.created_at) {
      const time=node("time","",new Date(item.created_at).toLocaleString([], {dateStyle:"medium",timeStyle:"short"}));
      time.dateTime=item.created_at;header.append(time);
    }
    copy.append(header,node("p","",item.text));row.append(avatar,copy);container.append(row);
  }
  if (atEnd || scrollToEnd) container.scrollTop=container.scrollHeight;
}
async function refreshThread(scrollToEnd=false) {
  const id=state.threadId,version=state.threadVersion;if (id===null)return;
  const items=await api(`/api/v1/cards/${id}/comments`);
  if (state.threadId!==id || version!==state.threadVersion)return;
  renderThread(items,scrollToEnd);updateCommentCount(id,items.length);
}
async function openThread(id,opener) {
  const version=++state.threadVersion;const card=state.cards.find(c=>c.id===id) || await api(`/api/v1/cards/${id}`);
  if (version!==state.threadVersion)return;
  state.threadId=id;$("#thread-reference").textContent=`Discussion · Card #${id}`;
  $("#thread-title").textContent=card.title;$("#thread-text").value="";
  $("#composer-avatar").textContent=initials(state.user.name);$("#composer-name").textContent=state.user.name;
  $("#thread-messages").dataset.signature="";$("#thread-messages").textContent="Loading replies…";
  notify("#thread-status");showDialog($("#thread-dialog"),opener);
  try {await refreshThread(true);} catch(e){notify("#thread-status",e.message,true);}
}
$("#open-discussion").addEventListener("click",event=>{
  if(state.selected!==null)openThread(state.selected,event.currentTarget).catch(e=>notify("#detail-message",e.message,true));
});
$("#thread-form").addEventListener("submit",event=>{
  event.preventDefault();const id=state.threadId;const version=state.threadVersion;
  action(event.currentTarget.querySelector("[type=submit]"),"#thread-status",async()=>{
    await postReply(id,$("#thread-text").value);
    if(state.threadId!==id || version!==state.threadVersion)return;
    $("#thread-text").value="";await refreshThread(true);notify("#thread-status","Reply posted.");
  });
});
setInterval(async()=>{
  if (!$("#thread-dialog").open || state.threadBusy)return;
  state.threadBusy=true;
  try {await refreshThread();} catch(e) {notify("#thread-status",`Could not refresh replies: ${e.message}`,true);}
  finally{state.threadBusy=false;}
},8000);

// The assistant renders readable, sanitized Markdown, never executable model HTML.
$("#assistant-open").addEventListener("click",event=>showDialog($("#assistant-dialog"),event.currentTarget));
function markdown(target,text) {
  if (!window.marked || !window.DOMPurify) {target.textContent=text;return;}
  const html=marked.parse(text,{breaks:true,gfm:true});
  target.innerHTML=DOMPurify.sanitize(html,{
    ALLOWED_TAGS:["p","br","strong","em","ul","ol","li","h1","h2","h3","h4","h5","h6","blockquote","pre","code","hr","a","table","thead","tbody","tr","th","td","del","s"],
    ALLOWED_ATTR:["href","title"],
    SANITIZE_NAMED_PROPS:true,
  });
  target.querySelectorAll("a").forEach(a=>{a.target="_blank";a.rel="noopener noreferrer";});
}
function drawChat() {
  const history=$("#chat-history");history.replaceChildren();
  if (!state.history.length) {
    const welcome=node("div","chat-welcome");welcome.append(node("span","sparkle","✧"),node("h3","","From an idea to a real plan."),node("p","","Talk it through, preview the cards, then approve creation and assignments separately."));history.append(welcome);
  }
  for (const m of state.history) {
    const bubble=node("div",`chat-bubble ${m.role}`);bubble.append(node("strong","chat-speaker",m.role==="user" ? "You" : "Planning partner"));
    const body=node("div",m.role==="assistant" ? "markdown" : "user-message");
    if(m.role==="assistant")markdown(body,m.display || m.content);else body.textContent=m.display || m.content;
    bubble.append(body);history.append(bubble);
  }
  history.scrollTop=history.scrollHeight;
  requestAnimationFrame(()=>{history.scrollTop=history.scrollHeight;});
}
function setChatBusy(busy) {
  state.chatBusy=busy;
  for(const selector of ["#chat-form [type=submit]","#clear-chat","#preview-plan","#suggest-assignments","#chat-input"])$(selector).disabled=busy;
  $("#proposal-panel").querySelectorAll("button").forEach(b=>{b.disabled=busy;});
}
async function chatAction(work) {
  if(state.chatBusy)return;
  setChatBusy(true);notify("#chat-message");
  try {await work();}catch(e){notify("#chat-message",e.message,true);}
  finally{setChatBusy(false);}
}
function cardName(id){return state.cards.find(c=>c.id===id)?.title || `Card #${id}`;}
function renderProposal() {
  const panel=$("#proposal-panel");panel.replaceChildren();panel.hidden=!state.proposal;
  if(!state.proposal)return;
  const p=state.proposal;
  panel.append(node("p","eyebrow",p.kind==="cards" ? "1 · Review cards before creating" : "2 · Review assignments before applying"));
  const list=node("div","proposal-items");
  if(p.kind==="cards") {
    for(const card of p.data.cards) {
      const item=node("details","proposed-card");
      const summary=node("summary","",card.title);item.append(summary,node("p","",card.goal));
      const criteria=node("ul");for(const text of card.acceptance_criteria)criteria.append(node("li","",text));
      item.append(node("strong","small","Acceptance criteria"),criteria);
      if(card.out_of_scope)item.append(node("p","muted small",`Out of scope: ${card.out_of_scope}`));
      list.append(item);
    }
  } else {
    for(const assignment of p.data.assignments) {
      const row=node("article","proposed-assignment");
      const person=state.people.find(p=>p.id===assignment.person_id);
      row.append(node("strong","",cardName(assignment.card_id)),node("span","assignment-choice",person ? `→ ${person.name}` : "→ Leave unassigned"),node("p","muted small",assignment.reason));list.append(row);
    }
  }
  panel.append(list,node("p","muted small",(p.kind==="cards" ? "No cards created yet. " : "No assignments applied yet. ")+"Preview expires after 30 minutes. Discuss a revision to replace it."));
  const controls=node("div","proposal-actions");
  const confirm=button(p.kind==="cards" ? `Create ${p.data.cards.length} ${p.data.cards.length===1 ? "card" : "cards"}` : "Yes, apply these assignments","button-primary");confirm.id="confirm-proposal";
  confirm.addEventListener("click",()=>chatAction(confirmProposal));
  const revise=button("Change this");revise.addEventListener("click",()=>chatAction(async()=>{
    await cancelProposal();$("#chat-input").placeholder="Tell me what should change…";$("#chat-input").focus();
  }));
  const dismiss=button("Dismiss");dismiss.addEventListener("click",()=>chatAction(cancelProposal));
  controls.append(confirm,revise,dismiss);panel.append(controls);
}
async function cancelProposal() {
  if(!state.proposal)return;
  try {
    await api(`/api/v1/assistant/proposals/${state.proposal.id}/cancel`,json("POST",{conversation_id:state.chatId}));
    state.proposal=null;renderProposal();notify("#chat-message","Preview dismissed. No changes were applied.");
  } catch(error) {
    if (/^HTTP (404|409|410):/.test(error.message)) {
      state.proposal=null;renderProposal();
      await loadBoard();
      notify("#chat-message","Preview cleared from this tab. Any previously saved changes remain on the board.");
      return;
    }
    throw error;
  }
}
async function requestAssistant(content,mode="discuss",targets=[]) {
  const previous=state.history.slice();
  if(previous.length>=38 || previous.reduce((n,m)=>n+m.content.length,0)+content.length>43000)throw new Error("This conversation is full. Start a new conversation before continuing.");
  state.history.push({role:"user",content});state.proposal=null;renderProposal();drawChat();
  notify("#chat-message",mode==="plan" ? "Drafting cards for your review…" : mode==="assign" ? "Matching tasks to your team…" : "Thinking…");
  try {
    const result=await api("/api/v1/assistant/chat",json("POST",{
      conversation_id:state.chatId,mode,target_card_ids:targets,
      messages:state.history.map(({role,content})=>({role,content})),
    }));
    const context=result.proposal ? `\nDraft proposal data (not applied): ${JSON.stringify(result.proposal.data)}` : "";
    state.history.push({role:"assistant",content:result.message+context,display:result.message});
    state.proposal=result.proposal || null;drawChat();renderProposal();
    notify("#chat-message",`${result.model === "application" ? "Workspace" : "Answered by "+result.model}. No changes applied by this message.`);
  }catch(error){state.history=previous;drawChat();throw error;}
}
function assignmentTargets() {
  const ids=state.lastCreated.length ? state.lastCreated : state.cards.filter(c=>!c.assignee && c.stage!=="Done").map(c=>c.id);
  if(!ids.length)throw new Error("There are no target cards. Create cards first, or unassign a card you want to allocate.");
  if(ids.length>12)throw new Error("This preview supports up to 12 cards. Start with a smaller plan.");
  return ids;
}
async function confirmProposal() {
  const proposal=state.proposal;if(!proposal)return;
  let receipt;
  try{
    receipt=await api(`/api/v1/assistant/proposals/${proposal.id}/confirm`,json("POST",{conversation_id:state.chatId,approve:true}));
  }catch(error){
    if(error.message.startsWith("HTTP 404") || error.message.startsWith("HTTP 409") || error.message.startsWith("HTTP 410")){state.proposal=null;renderProposal();}
    throw error;
  }
  state.proposal=null;renderProposal();state.loadVersion++;
  receipt.cards.forEach(upsert);
  state.history.push({role:"assistant",content:`Application receipt: ${receipt.message} Card IDs: ${receipt.cards.map(c=>c.id).join(", ")}.`,display:receipt.message});drawChat();
  if(receipt.kind==="cards") {
    state.lastCreated=receipt.cards.map(c=>c.id);$("#suggest-assignments").hidden=false;
    // Card creation is already committed. Failure to draft assignments must not
    // hide that success or create the cards a second time.
    try {
      await requestAssistant("The application created these cards: "+receipt.cards.map(c=>`#${c.id} ${c.title}`).join("; ")+". Suggest who should own each one and ask for my approval before assigning.","assign",state.lastCreated);
    } catch(error) {notify("#chat-message",`${receipt.message} Assignment suggestions failed: ${error.message} Use Suggest assignments to retry.`,true);}
  }else notify("#chat-message",receipt.message);
}
$("#preview-plan").addEventListener("click",()=>chatAction(async()=>{
  const input=$("#chat-input");const draft=input.value.trim();
  await requestAssistant(draft ? `${draft}\nPrepare a card preview for the agreed plan.` : "Prepare a card preview for the plan we have discussed.","plan");input.value="";
}));
$("#suggest-assignments").addEventListener("click",()=>chatAction(()=>requestAssistant("Suggest assignments for these cards using our team's skills. Ask before applying them.","assign",assignmentTargets())));
$("#clear-chat").addEventListener("click",()=>chatAction(async()=>{
  if(state.history.length && !confirm("Start a new conversation? This clears the conversation in this tab, not your cards."))return;
  if(state.proposal)await cancelProposal();
  state.history=[];state.chatId=crypto.randomUUID();state.proposal=null;state.lastCreated=[];
  $("#suggest-assignments").hidden=true;drawChat();renderProposal();notify("#chat-message");
}));
$("#chat-form").addEventListener("submit",event=>{
  event.preventDefault();const input=$("#chat-input");const content=input.value.trim();if(!content)return;
  chatAction(async()=>{
    const normalized=content.toLowerCase().replace(/[.!?]+$/g,"").trim();
    if(state.proposal && ["yes","confirm","approve","go ahead","yes do it","yes assign them"].includes(normalized)) {
      await confirmProposal();input.value="";return;
    }
    const wantsPlan=/^(deploy|create|apply|put) (?:(?:the|this|my|our|these) )?(plan|cards|tasks)(?: (?:please|now|on the board))?$/.test(normalized);
    const wantsAssignment=/^(suggest assignments|assign them|assign the cards|assign these cards)$/.test(normalized);
    await requestAssistant(content,wantsPlan ? "plan" : wantsAssignment ? "assign" : "discuss",wantsAssignment ? assignmentTargets() : []);
    input.value="";
  });
});
async function enterWorkspace(user) {
  state.user=user;$("#auth-screen").hidden=true;$("#workspace").hidden=false;
  $("#account-open").replaceChildren(node("span","avatar",initials(user.name)),node("span","account-name",user.name));
  $("#person-form").hidden=!user.is_admin;
  $("#account-description").textContent=`${user.name} · @${user.username}${user.is_admin ? " · Workspace owner" : ""}`;
  await Promise.all([loadBoard(),loadPeople()]);
}
function expireSession() {
  state.authEpoch++;state.user=null;state.cards=[];state.people=[];state.history=[];state.proposal=null;
  state.threadId=null;state.threadVersion++;state.loadVersion++;state.chatId=crypto.randomUUID();
  state.lastCreated=[];$("#suggest-assignments").hidden=true;drawChat();renderProposal();
  for (const dialog of document.querySelectorAll("dialog[open]"))dialog.close();
  $("#board").replaceChildren();$("#workspace").hidden=true;$("#auth-screen").hidden=false;
  configureAuth("login");
}
function configureAuth(mode, name="") {
  state.authMode=mode;const setup=mode==="setup",invite=mode==="invite";
  if(!setup)$("#auth-profile-field").hidden=true;
  $("#auth-screen").hidden=false;$("#auth-name-field").hidden=!setup;$("#auth-name").required=setup;
  $("#auth-heading").textContent=setup ? "Create your workspace." : invite ? `Welcome, ${name}.` : "Sign in.";
  $("#auth-eyebrow").textContent=setup ? "A fresh start" : invite ? "You’re invited" : "Welcome back";
  $("#auth-description").textContent=setup ? "Choose your owner account. You can invite your team next." : invite ? "Choose your own login to join the shared board." : "Your cards and conversations are waiting.";
  $("#auth-submit").textContent=setup ? "Create workspace" : invite ? "Join workspace" : "Sign in";
  $("#auth-password").autocomplete=setup || invite ? "new-password" : "current-password";
  $("#password-hint").textContent=setup || invite ? "Use at least 12 characters. A unique passphrase works well." : "Use the password you chose for this workspace.";
  $("#auth-help").textContent=setup ? "Saved on this computer in a local SQLite database." : invite ? "This invitation is personal and can only be used once." : "Need an account? Ask the workspace owner for an invitation.";
}
$("#auth-profile").addEventListener("change",()=>{const select=$("#auth-profile");if(select.value)$("#auth-name").value=select.selectedOptions[0].textContent;});
$("#auth-form").addEventListener("submit",event=>{
  event.preventDefault();const form=event.currentTarget;
  action($("#auth-submit"),"#auth-error",async()=>{
    const body={username:$("#auth-username").value.trim(),password:$("#auth-password").value};
    if(state.authMode==="setup"){body.name=$("#auth-name").value.trim();if($("#auth-profile").value)body.person_id=Number($("#auth-profile").value);}
    if(state.authMode==="invite")body.token=state.inviteToken;
    const route=state.authMode==="invite" ? "accept-invite" : state.authMode;
    const user=await api(`/api/v1/auth/${route}`,json("POST",body));
    form.reset();state.inviteToken=null;await enterWorkspace(user);
  });
});
$("#account-open").addEventListener("click",event=>showDialog($("#account-dialog"),event.currentTarget));
$("#sign-out").addEventListener("click",event=>action(event.currentTarget,"#account-message",async()=>{
  if(state.chatBusy)throw new Error("Wait for the current assistant action to finish before signing out.");
  await api("/api/v1/auth/logout",json("POST",{}));expireSession();$("#auth-form").reset();notify("#auth-error");
}));
$("#copy-invite").addEventListener("click",event=>action(event.currentTarget,"#invite-message",async()=>{
  try{await navigator.clipboard.writeText($("#invite-url").value);notify("#invite-message","Link copied. Share it privately.");}
  catch{ $("#invite-url").select();notify("#invite-message","Select the link and press Ctrl+C to copy it.");}
}));
async function start() {
  const token=new URLSearchParams(location.hash.slice(1)).get("invite");
  if(token){
    history.replaceState(null,"",location.pathname);state.inviteToken=token;
    const invitation=await api("/api/v1/auth/invitation",json("POST",{token}));
    configureAuth("invite",invitation.name);return;
  }
  const status=await api("/api/v1/auth/status");
  if(status.setup_required){
    const people=status.existing_people || [];$("#auth-profile-field").hidden=!people.length;
    for(const p of people)$("#auth-profile").add(new Option(p.name,String(p.id)));
    configureAuth("setup");return;
  }
  try{const user=await api("/api/v1/auth/me");await enterWorkspace(user);}
  catch(error){configureAuth("login");if(!error.message.startsWith("HTTP 401"))notify("#auth-error",error.message,true);}
}
start().catch(error=>{configureAuth("login");notify("#auth-error",error.message,true);});
