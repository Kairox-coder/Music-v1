fetch("WORKER_URL/stats")
.then(r=>r.json())
.then(d=>{
document.getElementById("stats").innerHTML=
"Total: "+d.total+"<br>"+d.top.map(x=>x.name+": "+x.plays).join("<br>");
});
