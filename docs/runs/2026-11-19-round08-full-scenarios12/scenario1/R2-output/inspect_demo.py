import re, subprocess
src = open("inbox/roombook.html", encoding="utf-8").read()
js = re.search(r"<script>(.*)</script>", src, re.S).group(1)
js = js.replace("state=load();\nrenderAll();", "state=load();\nrenderAll();\nglobal.__t={renderDash:renderDash,renderAll:renderAll,setState:function(s){state=s;},getState:function(){return state;},demo:demo};")
open("extracted_test.js", "w", encoding="utf-8").write(js)
test = r'''
const fs=require("fs");
const js=fs.readFileSync("extracted_test.js","utf8");
function makeEl(id){return {id,value:"",innerHTML:"",textContent:"",classList:{add(){},remove(){},toggle(){}},addEventListener(){},setAttribute(){},getAttribute(){return null;},querySelectorAll(){return [];},appendChild(){},click(){}};}
const els={};global.document={getElementById:id=>els[id]||(els[id]=makeEl(id)),querySelectorAll:()=>[],createElement:()=>makeEl("x")};
global.localStorage={getItem(){return null;},setItem(){}};global.confirm=()=>true;global.prompt=()=>null;global.URL={createObjectURL(){return "";}};global.Blob=function(){};global.FileReader=function(){};global.setTimeout=()=>0;global.clearTimeout=()=>{};global.window=global;
eval(js);
const T=global.__t, d=T.demo();
const byRoom={},byDay={};
d.bookings.forEach(b=>{byRoom[b.roomId]=(byRoom[b.roomId]||0)+1;byDay[b.date]=(byDay[b.date]||0)+1;});
console.log("rooms",d.rooms.map(r=>r.id+":"+r.name).join(" "));
console.log("bookings",d.bookings.length,"cancelled",d.cancelled.length);
console.log("byRoom",JSON.stringify(byRoom));
console.log("distinct days",Object.keys(byDay).length,"max/day",Math.max(...Object.values(byDay)));
const hours=d.bookings.reduce((a,b)=>a+(b.end-b.start),0)/60;
console.log("total hours",hours);
// weekday distribution
const wd={};d.bookings.forEach(b=>{const k=new Date(b.date+"T00:00").getDay();wd[k]=(wd[k]||0)+1;});console.log("weekday",JSON.stringify(wd));
// hour distribution
const hr={};d.bookings.forEach(b=>{for(let m=b.start;m<b.end;m+=30){const h=Math.floor(m/60);hr[h]=(hr[h]||0)+1;}});console.log("hours",JSON.stringify(hr));
// overlap check
let ov=0;for(let i=0;i<d.bookings.length;i++)for(let j=i+1;j<d.bookings.length;j++){const a=d.bookings[i],b=d.bookings[j];if(a.roomId===b.roomId&&a.date===b.date&&a.start<b.end&&b.start<a.end)ov++;}
console.log("overlaps",ov);
// cancelled dates in past?
const today=new Date();const iso=x=>x.toISOString().slice(0,10);
console.log("cancelled dates",d.cancelled.map(c=>c.date).join(","));
console.log("cancelledAt sample",d.cancelled[0].cancelledAt, d.cancelled[0].cancelledBy);
'''
open("t2.js","w").write(test)
r=subprocess.run(["node","t2.js"],capture_output=True,text=True)
print(r.stdout); print(r.stderr[-1500:])
