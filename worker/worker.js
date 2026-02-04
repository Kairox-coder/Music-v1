export default{
async fetch(){
const r=await fetch("https://sheets.googleapis.com/v4/spreadsheets/YOUR_SHEET/values/users?key=APIKEY")
const d=await r.json()
let u=d.values.slice(1).map(x=>({name:x[1],plays:+x[2]}))
u.sort((a,b)=>b.plays-a.plays)
return new Response(JSON.stringify({total:u.reduce((a,b)=>a+b.plays,0),top:u.slice(0,10)}))
}}
