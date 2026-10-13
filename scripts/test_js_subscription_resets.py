#!/usr/bin/env python3
"""Actual reset UI: read-only render, confirmation and stable retries, no real account."""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _node import find_node
ROOT=Path(__file__).resolve().parent.parent
PROBE=r'''
import assert from "node:assert/strict";
const calls=[], notices=[], refreshed=[], confirmations=[];
let agreed=false, failure=false, rejected=false;
const account={id:"a",name:"Owner <A>",oauthEmail:"a@example.test",hasCredential:true};
const payload={availableCount:3,credits:[{id:"c",resetType:"codex_rate_limits",usable:true,expiresAt:"2030-01-01T00:00:00Z"},{id:"other",resetType:"codex_rate_limits",usable:true}],pending:[]};
globalThis.__stubReturns={
 "i18n.t":(k,p)=> k+JSON.stringify(p||{}),
 "utils.escapeHtml":x=>String(x??"").replaceAll("<","&lt;").replaceAll('"',"&quot;"),
 "utils.toast":x=>notices.push(x),
 "dialogs.appConfirm":async(message,opts)=>{confirmations.push([message,opts]);return agreed;},
 "utils.api":async(path,options)=>{
   const body=options?.body?JSON.parse(options.body):null;calls.push([path,body]);
   if(path.includes("subscription-resets?"))return structuredClone(payload);
   assert.equal(path,"/api/cloud-accounts/subscription-reset");
   assert.equal(body.confirmed,true);
   if(rejected)throw Error("selected credit expired before spend");
   if(failure){payload.pending=[{creditId:body.creditId,idempotencyKey:body.idempotencyKey}];throw Error("timeout");}
   payload.pending=[]; payload.availableCount=2;payload.credits[0].usable=false;
   return {ok:true,outcome:"reset"};
 }
};
const {SubscriptionResetCards}=await import("../static/js/subscription-resets.js");
let picked=null;const asked=[];
const choice=async(message,opts)=>{asked.push([message,opts]);return picked;};
const cards=new SubscriptionResetCards({refreshed:id=>refreshed.push(id),choice});
assert.equal(cards.count(account),null); // nothing read yet: unknown, not "0 resets"
assert.equal(cards.pending(account),false);
assert.equal(cards.failed(account),false); // unread is not failed
// the counter reads its own resets (1.3.464: no list under the fold asks for them any more)
cards.read({id:"unconnected",hasCredential:false});
assert.equal(calls.length,0); // no sign-in, nothing asked
cards.read(account);await new Promise((r)=>setImmediate(r));
assert.equal(cards.count(account),3);
assert.equal(cards.count({...account,id:"alias",testAliasOf:"a"}),3); // a TEST member shows its original's balance
cards.read(account);await new Promise((r)=>setImmediate(r));
assert.equal(calls.length,1); // within a minute the counter does not ask again
assert.equal(calls.filter(c=>c[1]).length,0); // reading cannot spend
await cards.choose(account);
assert.equal(calls.filter(c=>c[1]).length,0); // Cancel cannot POST
assert.ok(asked.at(-1)[0].includes("Owner <A>"));
picked="c";failure=true;
await cards.choose(account);
const first=calls.find(c=>c[1]);
assert.equal(first[1].creditId,"c");
assert.match(first[1].idempotencyKey,/^[0-9a-f-]{36}$/);
assert.equal(cards.pending(account),true); // the head of a rung can say it
assert.equal(cards.pending({...account,id:"alias",testAliasOf:"a"}),true);
assert.equal(cards.pending({id:"other-account"}),false);
const reloaded=new SubscriptionResetCards({refreshed:id=>refreshed.push(id),choice});
await reloaded.fetch("a");
assert.equal(reloaded.attempts.get("a").idempotencyKey,first[1].idempotencyKey);
const count=calls.filter(c=>c[1]).length;
picked="other";
await reloaded.choose(account);
assert.equal(calls.filter(c=>c[1]).length,count); // an unresolved spend blocks another
failure=false;picked="c";
await reloaded.choose(account);
const posts=calls.filter(c=>c[1]);
assert.equal(posts.length,2);
assert.equal(posts[1][1].idempotencyKey,first[1].idempotencyKey);
assert.deepEqual(refreshed,["a"]);
assert.equal(reloaded.attempts.size,0);
assert.equal(reloaded.pending(account),false);
assert.equal(reloaded.count(account),2);
rejected=true;
const refused=new SubscriptionResetCards({choice:async()=>"other"});
await refused.fetch("a");
await refused.choose(account);
assert.equal(refused.attempts.size,0); // a refused spend must not lock all other credits
assert.equal(refused.pending(account),false);
const failed=new SubscriptionResetCards();
globalThis.__stubReturns["utils.api"]=async()=>{throw Error("offline");};
await failed.fetch("a");
assert.equal(failed.count(account),null); // a failed read is not zero
assert.equal(failed.failed(account),true); // ... and the counter says "?" instead of vanishing
globalThis.__stubReturns["utils.api"]=async()=>({availableCount:"3",credits:[],pending:[]});
const odd=new SubscriptionResetCards();
await odd.fetch("a");
assert.equal(odd.count(account),null); // only a number is a count
assert.equal(odd.failed(account),false); // a read that answered is not a failed read
assert.equal(typeof SubscriptionResetCards.prototype.html,"undefined"); // the rows under a fold are gone
// ── the small door on a subscription's row of the main board (the owner, 2026-10-12) ──
const chip=(c,a)=>c.chipHtml(a);
assert.equal(chip(new SubscriptionResetCards(),account),""); // a count not read yet draws nothing — not "↺ 0"
assert.ok(chip(failed,account).includes(">↺ ?</span>") && chip(failed,account).includes('data-t-state="unknown"')); // a failed read says "?"
assert.ok(!chip(failed,account).includes("data-pool-resets")); // ... and is no button
const two=chip(reloaded,account);
assert.ok(two.startsWith('<button class="pool-resets" type="button" data-pool-resets="a" data-t="provider-resets" data-t-state="some"') && two.endsWith(">↺ 2</button>") && !two.includes("⚠"));
assert.ok(chip(reloaded,{...account,id:"alias",testAliasOf:"a"}).includes('data-pool-resets="a"')); // a TEST copy opens its original's
const none=new SubscriptionResetCards();none.cache.set("a",{data:{availableCount:0},at:0});
assert.ok(chip(none,account).includes(">↺ 0</span>") && !chip(none,account).includes("<button")); // none to spend: the count alone
const pend=chip(cards,account);
assert.ok(pend.startsWith('<span class="pool-warn"') && pend.indexOf("⚠")<pend.indexOf("↺")); // an unresolved spend: ⚠ ahead of the door
assert.equal(typeof SubscriptionResetCards.prototype.handle,"undefined");
// ── the counter's door: a window of choice; its own button is the confirmation ──
const creds=[
 {id:"late",resetType:"codex_rate_limits",usable:true,expiresAt:"2031-03-01T00:00:00Z"},
 {id:"soon",resetType:"codex_rate_limits",usable:true,expiresAt:"2030-06-01T00:00:00Z"},
 {id:"open",resetType:"codex_rate_limits",usable:true},
 {id:"spent",resetType:"codex_rate_limits",usable:false,expiresAt:"2029-01-01T00:00:00Z"},
 {id:"odd",resetType:"other_type",usable:false,title:"Other",expiresAt:"2029-02-01T00:00:00Z"},
];
const O=SubscriptionResetCards.options, vals=(o)=>o.map(x=>x.value);
assert.deepEqual(vals(O(creds,null)),["soon","late","open"],"only what can be spent; the one that ends first leads; no end date last");
assert.deepEqual(creds.map(c=>c.id),["late","soon","open","spent","odd"],"the cache's own list is not reordered");
assert.deepEqual(O(creds.map(c=>({...c,usable:false})),null),[],"nothing can be spent: nothing is offered");
assert.deepEqual(O(undefined,null),[]);assert.deepEqual(O(null,null),[]);
assert.deepEqual(vals(O([{id:"x",usable:true,expiresAt:"nonsense"},{id:"y",usable:true,expiresAt:"2030-01-01T00:00:00Z"}],null)),["y","x"],"a date nobody can read counts as no date");
const labelled=O(creds,null);
assert.ok(labelled[0].label.startsWith("resetFull{} · resetExpires")&&labelled[2].label==="resetFull{}","title · when it ends; no end date, no dangling separator");
assert.equal(O([{id:"o",resetType:"other_type",usable:true,title:"Other"}],null)[0].label,"Other","another kind of reset is named by the provider");
assert.equal(O([{id:"o",resetType:"other_type",usable:true}],null)[0].label,'poolUnavailable{}',"a reset nobody named is 'unavailable', not guessed");
assert.deepEqual(O(creds,{creditId:"late"}).map(x=>x.value),["late"],"an unresolved attempt: that reset only");
assert.deepEqual(O(creds,{creditId:"gone"}),[{value:"gone",label:"resetRetry{}"}],"the unresolved one is offered even when the list no longer shows it");
const world={credits:creds,pending:[],count:5,outcome:"reset",fail:false}, posted=[]; let gets=0, clock=1000;
picked=null;asked.length=0;
globalThis.__stubReturns["utils.api"]=async(path,options)=>{
 const body=options?.body?JSON.parse(options.body):null;
 if(body){posted.push(body);assert.equal(body.confirmed,true);if(world.fail)throw Error("boom");return {ok:true,outcome:world.outcome};}
 gets++;return structuredClone({availableCount:world.count,credits:world.credits,pending:world.pending});
};
notices.length=0;refreshed.length=0;asked.length=0;
const door=new SubscriptionResetCards({now:()=>clock,refreshed:id=>refreshed.push(id),choice:async(message,opts)=>{asked.push([message,opts]);return picked;}});
await door.choose(account);
assert.equal(asked.length,1);
const [message,opts]=asked[0];
assert.ok(message.includes('resetConfirm{"account":"Owner <A>"}')&&!message.includes("resetPending"),"the question names the account; no word about an unresolved reset when there is none");
assert.deepEqual([opts.title,opts.confirmLabel,opts.danger,opts.detail,opts.list],["resetConfirmTitle{}","resetUse{}",true,"a@example.test",true],"a dangerous question: spending is final; the mailbox says whose");
assert.deepEqual(opts.choices.map(c=>c.value),["soon","late","open"],"the window offers what options() offers");
assert.equal(opts.choiceLabel,'resetAvailable{"count":"3"}',"counts what is offered, not what the provider says it has (5)");
assert.equal(posted.length,0,"cancel: nothing sent");
assert.equal(door.busy.size,0,"cancel: not left busy");
assert.equal(door.attempts.size,0,"cancel: nothing stored");
assert.deepEqual(notices,[]);
picked="late";
await door.choose(account);
assert.equal(posted.length,1);
assert.deepEqual([posted[0].id,posted[0].creditId],["a","late"],"the reset that was chosen, on the credential that was named");
assert.match(posted[0].idempotencyKey,/^[0-9a-f-]{36}$/);
assert.deepEqual(notices.at(-1),"resetDone{}");
assert.deepEqual(refreshed,["a"],"a spent reset: the limits are read again");
assert.equal(door.attempts.size,0);
assert.equal(door.busy.size,0);
// an empty answer is no answer
picked="";const before=posted.length;
await door.choose(account);
assert.equal(posted.length,before,"nothing chosen: nothing spent");
// nothing to choose from: said, not shown as an empty window
world.credits=creds.map(c=>({...c,usable:false}));clock+=61000;notices.length=0;asked.length=0;
await door.choose(account);
assert.equal(asked.length,0,"no window without a choice in it");
assert.equal(notices.at(-1),"resetNoCredit{}");
world.credits=creds;
// a list older than a minute is read again before the window opens; a fresh one is not
clock+=61000;let g0=gets;picked=null;
await door.choose(account);
assert.equal(gets,g0+1,"stale: read again");
g0=gets;clock+=59000;
await door.choose(account);
assert.equal(gets,g0,"fresh: asked of nobody");
// an unresolved attempt: one reset, and the window says why
world.pending=[{creditId:"late",idempotencyKey:"11111111-1111-4111-8111-111111111111"}];clock+=61000;asked.length=0;picked="late";posted.length=0;
await door.choose(account);
const [pm,po]=asked[0];
assert.deepEqual(po.choices.map(c=>c.value),["late"]);
assert.ok(pm.includes("resetConfirm")&&pm.includes("resetPending"),"the window says why it offers one reset only");
assert.deepEqual([po.confirmLabel,po.choiceLabel],["resetRetry{}","resetRetry{}"]);
assert.equal(posted[0].idempotencyKey,"11111111-1111-4111-8111-111111111111","a retry keeps the key it was made with");
assert.equal(posted[0].creditId,"late");
// the window cannot be made to spend another reset while one is unresolved
world.pending=[{creditId:"late",idempotencyKey:"11111111-1111-4111-8111-111111111111"}];clock+=61000;picked="soon";posted.length=0;
await door.choose(account);
assert.equal(posted.length,0,"another reset: refused before it is sent");
assert.equal(door.busy.size,0);
world.pending=[];clock+=61000;
// busy: a second press while the window is open opens no second window
let release;const slow=new SubscriptionResetCards({now:()=>clock,choice:()=>new Promise((r)=>{release=r;})});
await slow.fetch("a");
const first_=slow.choose(account);
await new Promise((r)=>setImmediate(r));
await slow.choose(account);
assert.ok(slow.busy.has("a"),"while the window is open the credential is busy");
release(null);await first_;
assert.equal(slow.busy.size,0);
// a TEST member spends its original's reset
const aliased=new SubscriptionResetCards({now:()=>clock,choice:async()=>"soon"});
posted.length=0;
await aliased.choose({...account,id:"alias",name:"Alias",testAliasOf:"a"});
assert.equal(posted[0].id,"a","resets belong to the credential, not to its test copy");
// a spend that fails: said, and the credential is free again
world.fail=true;posted.length=0;notices.length=0;
const broken=new SubscriptionResetCards({now:()=>clock,choice:async()=>"soon"});
await broken.choose(account);
assert.equal(notices.at(-1),"boom");
assert.equal(broken.busy.size,0);
world.fail=false;
console.log("reset UI OK: the counter reads its own resets, unknown and failed apart from zero, cancel, stable retries after reload, quota refresh, rejection recovery, the small door on a row, the counter's window of choice — the one door");
'''
probe=ROOT/'scripts/.probe_resets.tmp.mjs'
probe.write_text(PROBE)
try:
 harness=ROOT/'scripts/_js_harness.mjs'
 result=subprocess.run([find_node(),'--import',f"data:text/javascript,import {{register}} from 'node:module';register('{harness.as_uri()}');",str(probe)],cwd=ROOT,env={**os.environ,'JS_ROOT':str(ROOT/'static/js'),'JS_STUBS':'i18n,utils,dialogs'},capture_output=True,text=True,timeout=20)
 print(result.stdout,end='');print(result.stderr,end='',file=sys.stderr)
finally: probe.unlink(missing_ok=True)
raise SystemExit(result.returncode)
