const canvas = document.getElementById("roadCanvas");
const ctx = canvas.getContext("2d");

const laneName = document.getElementById("laneName");
const jsonPreview = document.getElementById("jsonPreview");

const img = new Image();

let lanes = [];
let currentLaneIndex = 0;

lanes.push({
  name: "Lane 1",
  points: []
});

img.onload = () => {
  canvas.width = img.width;
  canvas.height = img.height;
  draw();
};

img.src = localStorage.getItem("snapshotImage");

canvas.addEventListener("click", e => {
  const rect = canvas.getBoundingClientRect();

  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;

  const x = Math.round((e.clientX - rect.left) * scaleX);
  const y = Math.round((e.clientY - rect.top) * scaleY);

  lanes[currentLaneIndex].points.push([x,y]);
  draw();
});

function draw(){
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.drawImage(img,0,0);

  lanes.forEach((lane, idx) => {
    const pts = lane.points;

    if(!pts.length) return;

    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);

    for(let i=1;i<pts.length;i++){
      ctx.lineTo(pts[i][0], pts[i][1]);
    }

    if(pts.length >= 3){
      ctx.closePath();
      ctx.fillStyle = idx === currentLaneIndex
        ? "rgba(0,255,0,.25)"
        : "rgba(0,120,255,.22)";
      ctx.fill();
    }

    ctx.strokeStyle = idx === currentLaneIndex ? "#22c55e" : "#3b82f6";
    ctx.lineWidth = 3;
    ctx.stroke();

    pts.forEach((p,n)=>{
      ctx.beginPath();
      ctx.arc(p[0],p[1],5,0,Math.PI*2);
      ctx.fillStyle = "#fff";
      ctx.fill();

      ctx.fillStyle = "#000";
      ctx.fillText(n+1, p[0]+8, p[1]-8);
    });
  });

  jsonPreview.textContent = JSON.stringify(lanes,null,2);
}

function newLane(){
  const next = lanes.length + 1;

  lanes.push({
    name: "Lane " + next,
    points:[]
  });

  currentLaneIndex = lanes.length - 1;
  laneName.textContent = lanes[currentLaneIndex].name;
  draw();
}

function undoPoint(){
  const pts = lanes[currentLaneIndex].points;
  pts.pop();
  draw();
}

function clearLane(){
  lanes[currentLaneIndex].points = [];
  draw();
}

async function savePolygons() {
  try {
    const res = await fetch("http://127.0.0.1:8000/save-polygons/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(lanes)
    });

    const data = await res.json();

    if(data.success){
      alert("Polygons saved successfully!");
    }else{
      alert("Failed to save");
    }

  } catch(err){
    console.error(err);
    alert("Server error");
  }
}