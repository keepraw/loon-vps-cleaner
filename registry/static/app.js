"use strict";
const $ = (id) => document.getElementById(id);
const T = {
  stats: "\u603b\u89c8", refresh: "\u5237\u65b0\u5168\u90e8\u673a\u573a", feeds: "Loon \u8ba2\u9605\u51fa\u53e3",
  sources: "\u673a\u573a\u8ba2\u9605\u6e90", nodes: "\u8282\u70b9\u7ba1\u7406", rules: "\u6301\u4e45\u6392\u9664\u6b63\u5219",
  add: "\u6dfb\u52a0\u5e76\u5237\u65b0", reload: "\u91cd\u65b0\u52a0\u8f7d", filter: "\u7b5b\u9009",
  exclude: "\u6392\u9664", keep: "\u4fdd\u7559", restore: "\u6062\u590d\u81ea\u52a8", edit: "\u4fee\u6539", copy: "\u590d\u5236\u8ba2\u9605",
  prev: "\u4e0a\u4e00\u9875", next: "\u4e0b\u4e00\u9875", save: "\u4fdd\u5b58", disable: "\u6682\u505c", enable: "\u542f\u7528",
  batchExclude: "\u6279\u91cf\u6392\u9664", batchKeep: "\u6279\u91cf\u6062\u590d", addRule: "\u65b0\u589e\u89c4\u5219",
  all: "\u5168\u90e8", reviewing: "\u5f85\u590d\u6838", accepted: "\u53ef\u7528", excluded: "\u5df2\u6392\u9664",
  display: "\u4fee\u6539\u663e\u793a\u540d\u79f0", saved: "\u64cd\u4f5c\u5df2\u4fdd\u5b58", failed: "\u64cd\u4f5c\u5931\u8d25",
  current: "\u5f53\u524d", source: "\u673a\u573a", state: "\u72b6\u6001", count: "\u8282\u70b9", manual: "\u624b\u52a8",
  region: "\u5730\u533a", empty: "\u6682\u65e0\u6570\u636e", refreshOne: "\u5355\u72ec\u5237\u65b0", warning: "\u8b66\u544a",
  hk:"\u9999\u6e2f", us:"\u7f8e\u56fd", jp:"\u65e5\u672c", overseas:"\u6d77\u5916\u5168\u90e8",
  allFeed:"\u7edf\u4e00\u8ba2\u9605\uff08\u5168\u90e8\u8282\u70b9\uff09",
  updated:"\u66f4\u65b0\u65f6\u95f4", status_auto:"\u81ea\u52a8", status_keep:"\u624b\u52a8\u4fdd\u7559",
  status_exclude:"\u624b\u52a8\u6392\u9664", status_review:"\u5f85\u786e\u8ba4",
  errorHint:"\u8bf7\u67e5\u770b\u670d\u52a1\u7aef\u65e5\u5fd7\u6216\u7a0d\u540e\u91cd\u8bd5"
};
let currentPage = 1;
let pageCount = 0;
let allSources = [];
let busy = false;
let nodesLoading = false;
const selected = new Map();

function txt(tag, text, cls = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function mkButton(label, handler, cls="") {
  const b = txt("button", label, cls);
  b.type = "button";
  b.addEventListener("click", handler);
  return b;
}
function when(ts) { return ts ? new Date(ts*1000).toLocaleString() : "--"; }
function toast(message, error=false) {
  const b = $("toast"); b.textContent = message; b.className = "show" + (error?" error":"");
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => b.className = "", 4800);
}
async function request(path, options={}) {
  const response = await fetch(path, {credentials:"same-origin", cache:"no-store", ...options});
  let body;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : (body?.detail?.message || `HTTP ${response.status}`);
    throw new Error(detail);
  }
  return body;
}
function json(method, path, payload) { return request(path, {method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)}); }
async function task(fn) {
  if (busy) return;
  busy = true; document.querySelectorAll("button").forEach(b => b.disabled = true);
  try { await fn(); } catch(e) { toast(`${T.failed}: ${e.message}`, true); }
  finally { busy=false; document.querySelectorAll("button").forEach(b => b.disabled=false); }
}
function localize() {
  const m = {"stats-heading":T.stats,"sync-all":T.refresh,"feeds-heading":T.feeds,
    "sources-heading":T.sources,"nodes-heading":T.nodes,"rules-heading":T.rules,
    "source-add-button":T.add,"nodes-reload":T.reload,"filter-apply":T.filter,
    "batch-exclude":T.batchExclude,"batch-keep":T.batchKeep,"page-prev":T.prev,
    "page-next":T.next,"rule-add-button":T.addRule};
  for(const [id,label] of Object.entries(m)) $(id).textContent=label;
  $("tagline").textContent="\u591a\u673a\u573a\u8ba2\u9605 / \u6c38\u4e45\u6392\u9664 / \u4e00\u4e2a\u8ba2\u9605\u3001\u56db\u4e2a\u624b\u52a8\u7b56\u7565\u7ec4";
  $("notice").textContent="\u6bcf\u5929\u5317\u4eac\u65f6\u95f4 05:00 \u5237\u65b0\uff1b\u4e0d\u81ea\u52a8\u6d4b\u901f\u3001\u4e0d\u5ef6\u8fdf\u6392\u5e8f\u3002";
  $("feeds-note").textContent="\u53ea\u9700\u5c06\u8fd9\u4e00\u4e2a\u8ba2\u9605\u5730\u5740\u6dfb\u52a0\u5230 Loon \u4e00\u6b21\u3002VPS \u4f1a\u7ed9\u8282\u70b9\u540d\u52a0\u4e0a HK - / US - / JP - \u524d\u7f00\uff0cLoon \u7528\u4e09\u4e2a\u8f7b\u91cf\u7b5b\u9009\u5668\u5efa\u7acb\u5730\u533a\u7b56\u7565\u7ec4\uff1b\u6d77\u5916\u7b56\u7565\u7ec4\u5305\u542b\u5168\u90e8\u8282\u70b9\u3002";
  $("rules-note").textContent="\u8f93\u5165\u6b63\u5219\u8868\u8fbe\u5f0f\u540e\uff0c\u6bcf\u6b21\u5237\u65b0\u90fd\u4f1a\u81ea\u52a8\u8fc7\u6ee4\u5339\u914d\u8282\u70b9\u3002\u4eba\u5de5\u4fdd\u7559\u7684\u8282\u70b9\u4f18\u5148\u7ea7\u66f4\u9ad8\u3002";
  const labels={"source-name-label":"\u673a\u573a\u540d\u79f0 ","source-url-label":"\u8ba2\u9605 HTTPS \u94fe\u63a5 ",
    "source-ua-label":"User-Agent\uff08\u53ef\u9009\uff09 ","filter-search-label":"\u641c\u7d22 ",
    "filter-source-label":"\u673a\u573a ","filter-status-label":"\u6807\u8bb0 ",
    "rule-pattern-label":"\u6b63\u5219 ","rule-source-label":"\u4f5c\u7528\u8303\u56f4 "};
  for(const [id,text] of Object.entries(labels)) $(id).firstChild.nodeValue = text;
  $("source-name").placeholder="\u673a\u573a A";
  $("node-q").placeholder="\u540d\u79f0\u6216\u670d\u52a1\u5668";
  for(const s of ["node-source","node-status","rule-source"]) $(s).options[0].textContent=T.all;
}
async function reloadStatus() {
  const stat = await request("/api/status");
  $("stats").replaceChildren();
  const entries = [[T.sources,stat.sources],[T.nodes,stat.nodes],[T.excluded,stat.excluded],[T.reviewing,stat.review]];
  for(const [label,value] of entries) {
    const div=document.createElement("div"); div.className="metric";
    div.append(txt("strong",String(value)),txt("span",label)); $("stats").append(div);
  }
}
async function reloadFeeds() {
  const feeds = await request("/api/feeds");
  $("feeds").replaceChildren();
  const info=feeds.all, wrap=txt("div","","feed"), data=document.createElement("div");
  data.append(txt("div",`${T.allFeed} : ${info.count} ${T.count}`,"name"),
    txt("div",`${T.updated}: ${when(info.published_at)}`,"subtext"));
  if(info.warning) data.append(txt("div",`${T.warning}: ${info.warning}`,"subtext"));
  const copy=mkButton(T.copy,async()=>{try{await navigator.clipboard.writeText(info.url);toast(T.saved);}catch(e){toast(e.message,true);}});
  wrap.append(data,copy); $("feeds").append(wrap);
}
async function reloadSources() {
  allSources = await request("/api/sources");
  $("sources").replaceChildren();
  for(const s of allSources) {
    const item=txt("div","","item"), data=document.createElement("div");
    data.append(txt("h3",s.name));
    data.append(txt("div",`${s.node_count} ${T.count} | ${T.updated}: ${when(s.last_success)} | ${s.enabled?T.enable:T.disable}`,"subtext"));
    if(s.last_error) data.append(txt("div",s.last_error,"subtext"));
    const actions=txt("div","","actions");
    actions.append(mkButton(T.refreshOne,()=>task(async()=>{const r=await request(`/api/sources/${s.id}/sync`,{method:"POST"});toast(`Updated: ${r.updated.length}, failed: ${r.failed.length}`);await reloadAll();})));
    actions.append(mkButton(s.enabled?T.disable:T.enable,()=>task(async()=>{await json("PATCH",`/api/sources/${s.id}`,{enabled:!s.enabled});await reloadAll();})));
    actions.append(mkButton(T.edit,()=>task(async()=>{
      const newName=prompt("Source name",s.name); if(newName===null||!newName.trim()) return;
      const newUrl=prompt("New HTTPS URL (leave blank to keep current)",""); if(newUrl===null)return;
      const payload={name:newName.trim()}; if(newUrl.trim())payload.url=newUrl.trim();
      await json("PATCH",`/api/sources/${s.id}`,payload);await reloadAll();
    })));
    item.append(data,actions);$("sources").append(item);
  }
  if(!allSources.length) $("sources").append(txt("p",T.empty,"empty"));
  for(const id of ["node-source","rule-source"]) {
    const sel=$(id), old=sel.value; sel.replaceChildren();
    sel.append(new Option(T.all,"")); for(const s of allSources)sel.append(new Option(s.name,s.id));
    if([...sel.options].some(o=>o.value===old))sel.value=old;
  }
}
async function reloadNodes() {
  if(nodesLoading) return;
  nodesLoading = true;
  $("page-prev").disabled = true;
  $("page-next").disabled = true;
  try {
  const query=new URLSearchParams({page:String(currentPage),page_size:"40",q:$("node-q").value,
    source_id:$("node-source").value,status_filter:$("node-status").value});
  const res=await request("/api/nodes?"+query.toString());
  pageCount=Math.ceil(res.total/40);
  $("nodes").replaceChildren();
  const fragment = document.createDocumentFragment();
  $("nodes-info").textContent=`${res.total} ${T.count}`;
  $("page-info").textContent=`${currentPage} / ${Math.max(1,pageCount)}`;
  if(!res.nodes.length) $("nodes").append(txt("p",T.empty,"empty"));
  for(const n of res.nodes){
    const id=n.source_id+":"+n.fingerprint;
    const item=txt("div","","item"), data=document.createElement("div"),title=txt("div","","nodehead");
    const ck=document.createElement("input"); ck.type="checkbox";ck.checked=selected.has(id);
    ck.addEventListener("change",()=>{if(ck.checked)selected.set(id,{source_id:n.source_id,fingerprint:n.fingerprint});else selected.delete(id);});
    title.append(ck,txt("h3",n.manual_alias||n.first_name));
    const effective = n.effective_reason ? (n.effective_reason==="needs_review"?"review":"exclude") : n.status;
    title.append(txt("span",T["status_"+effective]||effective,"tag "+effective));
    data.append(title,txt("div",`${n.source_name} | ${n.protocol} | ${n.server}:${n.port} | ${T.region}: ${T[n.effective_region]}`,"subtext"));
    if(n.last_name!==n.first_name) data.append(txt("div",`Upstream: ${n.last_name}`,"subtext"));
    if(n.review_reason) data.append(txt("div",`Review: ${n.review_reason}`,"subtext"));
    const actions=txt("div","","actions");
    if(n.status!=="exclude") actions.append(mkButton(T.exclude,()=>changeNode(n,{status:"exclude"}),"danger"));
    else actions.append(mkButton(T.restore,()=>changeNode(n,{status:"auto"})));
    if(n.status!=="keep") actions.append(mkButton(T.keep,()=>changeNode(n,{status:"keep"})));
    actions.append(mkButton(T.display,async()=>{
      const value=prompt("Stable display name (blank resets)",n.manual_alias||n.first_name);
      if(value!==null) await changeNode(n,{manual_alias:value});
    }));
    const sel=document.createElement("select");
    const opts=[["auto","Auto"],["hk",T.hk],["us",T.us],["jp",T.jp],["overseas",T.overseas]];
    for(const [v,text] of opts)sel.add(new Option(text,v));sel.value=n.region_override||"auto";
    sel.addEventListener("change",()=>changeNode(n,{region_override:sel.value}));
    actions.append(sel);
    if(n.global_excluded) actions.append(mkButton("Global Restore",()=>changeNode(n,{global_exclude:false})));
    else actions.append(mkButton("Global Exclude",()=>changeNode(n,{global_exclude:true})));
    item.classList.add("node-item");
    item.append(data,actions);
    fragment.append(item);
  }
  $("nodes").append(fragment);
  } finally {
    nodesLoading = false;
    $("page-prev").disabled = currentPage <= 1;
    $("page-next").disabled = currentPage >= pageCount;
  }
}
async function changeNode(n,patch){
  await task(async()=>{
    await json("PUT",`/api/nodes/${n.source_id}/${n.fingerprint}`,patch);
    await Promise.all([reloadNodes(),reloadFeeds(),reloadStatus()]);toast(T.saved);
  });
}
async function reloadRules(){
  const rules=await request("/api/rules");$("rules").replaceChildren();
  for(const r of rules){
    const item=txt("div","","item"),data=document.createElement("div"),actions=txt("div","","actions");
    const source=allSources.find(s=>s.id===r.source_id)?.name||T.all;
    data.append(txt("h3",r.pattern),txt("div",`${T.source}: ${source}`,"subtext"));
    actions.append(mkButton(T.exclude,()=>task(async()=>{await request(`/api/rules/${r.id}`,{method:"DELETE"});await reloadAll();}),"danger"));
    item.append(data,actions);$("rules").append(item);
  }
  if(!rules.length)$("rules").append(txt("p",T.empty,"empty"));
}
async function reloadAll(){
  // Independent sections should render as soon as their own API finishes.
  const results=await Promise.allSettled([
    reloadStatus(),reloadFeeds(),reloadSources(),reloadNodes(),reloadRules()
  ]);
  const failed=results.find(r=>r.status==="rejected");
  if(failed)throw failed.reason;
}

$("source-add").addEventListener("submit",e=>{e.preventDefault();task(async()=>{
  const payload={name:$("source-name").value.trim(),url:$("source-url").value.trim(),ua:$("source-ua").value.trim()};
  const added=await json("POST","/api/sources",payload);$("source-url").value="";
  try {const result=await request(`/api/sources/${added.id}/sync`,{method:"POST"});
    toast(`Imported: ${result.updated.length}; failed: ${result.failed.length}`);
  } catch(error){toast(`Source added; refresh failed: ${error.message}`,true);}
  await reloadAll();
});});
$("sync-all").addEventListener("click",()=>task(async()=>{const r=await request("/api/sync",{method:"POST"});await reloadAll();toast(`Updated: ${r.updated.length}; failed: ${r.failed.length}`);}));
$("nodes-reload").addEventListener("click",()=>reloadNodes().catch(e=>toast(e.message,true)));
$("filter-apply").addEventListener("click",()=>{currentPage=1;selected.clear();reloadNodes().catch(e=>toast(e.message,true));});
$("page-prev").addEventListener("click",()=>{if(currentPage>1){currentPage--;reloadNodes();}});
$("page-next").addEventListener("click",()=>{if(currentPage<pageCount){currentPage++;reloadNodes();}});
async function batch(status){if(!selected.size){toast("Please select nodes",true);return;}
  await task(async()=>{await json("POST","/api/nodes/batch",{nodes:[...selected.values()],status});selected.clear();await Promise.all([reloadNodes(),reloadFeeds(),reloadStatus()]);toast(T.saved);});
}
$("batch-exclude").addEventListener("click",()=>batch("exclude"));
$("batch-keep").addEventListener("click",()=>batch("auto"));
$("rule-add").addEventListener("submit",e=>{e.preventDefault();task(async()=>{
  await json("POST","/api/rules",{pattern:$("rule-pattern").value,source_id:$("rule-source").value||null});
  $("rule-pattern").value="";await reloadAll();toast(T.saved);
});});
localize();reloadAll().catch(e=>toast(e.message,true));
