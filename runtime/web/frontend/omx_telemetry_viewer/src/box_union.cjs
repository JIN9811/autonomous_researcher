// Exact exposed surface of an axis-aligned box union; internal contacts disappear.
function boxUnion(boxes) {
  const bounds=boxes.map(b=>b.position.map((v,i)=>[v-b.size[i]/2,v+b.size[i]/2]));
  const axes=[0,1,2].map(a=>[...new Set(bounds.flatMap(b=>b[a]).map(v=>Number(v.toFixed(9))))].sort((a,b)=>a-b));
  const occupied=new Set(), key=(i,j,k)=>`${i},${j},${k}`;
  for(let i=0;i<axes[0].length-1;i++)for(let j=0;j<axes[1].length-1;j++)for(let k=0;k<axes[2].length-1;k++) {
    const ids=[i,j,k], p=ids.map((n,a)=>(axes[a][n]+axes[a][n+1])/2);
    if(bounds.some(b=>p.every((v,a)=>v>b[a][0]-1e-10&&v<b[a][1]+1e-10)))occupied.add(key(i,j,k));
  }
  const quads=[];
  for(const cell of occupied){const ids=cell.split(',').map(Number);
    for(let a=0;a<3;a++)for(const sign of [-1,1]){
      const neighbor=[...ids];neighbor[a]+=sign;
      if(occupied.has(key(...neighbor)))continue;
      const u=(a+1)%3,v=(a+2)%3,coord=axes[a][ids[a]+(sign===1?1:0)];
      let points=[[0,0],[1,0],[1,1],[0,1]].map(([du,dv])=>{const p=[];p[a]=coord;p[u]=axes[u][ids[u]+du];p[v]=axes[v][ids[v]+dv];return p;});
      if(sign<0)points.reverse();
      quads.push({points,axis:a,sign});
    }
  }
  return quads;
}
module.exports={boxUnion};
