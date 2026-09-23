/* Rigid edge alignment: measured widths and shape are never stretched. */
window.PlanGeometry={
  units(panels) {
    const used=new Set();
    return panels.flatMap(p=>{
      if(used.has(p.key))return [];
      const pair=p.corner_group?panels.filter(v=>v.corner_group===p.corner_group):[p];
      const members=pair.length===2?pair:[p];members.forEach(v=>used.add(v.key));
      const label=members.length===2?p.label.replace(/\s*[ab]$/i,'')+' A/B':p.label;
      // Keep both measured arms for editing, identities, coupes and existing fiches.
      return [{members,label,outline:members.length===2?this.unionOutline(...members.map(v=>v.points)):p.points}];
    });
  },
  unionOutline(first,second) {
    // Split edges at intersections, then retain only the exterior union boundary.
    // No convex hull: it would fill the empty inside of an L or bridge a real gap.
    const cross=(a,b)=>a[0]*b[1]-a[1]*b[0],sub=(a,b)=>[a[0]-b[0],a[1]-b[1]],dist=(a,b)=>Math.hypot(...sub(a,b));
    const polygons=[first,second].map(poly=>{
      const area=poly.reduce((s,a,i)=>s+cross(a,poly[(i+1)%poly.length]),0);
      return area<0?[...poly].reverse():poly;
    });
    const scale=Math.max(1,...polygons.flatMap(poly=>poly.map((p,i)=>dist(p,poly[(i+1)%poly.length])))),eps=scale*1e-7;
    const inside=(p,poly)=>poly.every((a,i)=>cross(sub(poly[(i+1)%poly.length],a),sub(p,a))>=0);
    const inUnion=p=>polygons.some(poly=>inside(p,poly)),edges=[];
    polygons.forEach((poly,index)=>poly.forEach((a,i)=>{
      const b=poly[(i+1)%poly.length],u=sub(b,a),len=dist(a,b),cuts=[0,1];
      if(len<=eps)return;
      const other=polygons[1-index];
      other.forEach((c,j)=>{
        const d=other[(j+1)%other.length],v=sub(d,c),den=cross(u,v);
        if(Math.abs(den)>eps*eps){
          const t=cross(sub(c,a),v)/den,s=cross(sub(c,a),u)/den;
          if(t>=0&&t<=1&&s>=0&&s<=1)cuts.push(t);
        }else if(Math.abs(cross(sub(c,a),u))<=eps*len){
          [c,d].forEach(p=>{const t=((p[0]-a[0])*u[0]+(p[1]-a[1])*u[1])/(len*len);if(t>0&&t<1)cuts.push(t);});
        }
      });
      cuts.sort((x,y)=>x-y);
      for(let j=1;j<cuts.length;j++){
        const at=t=>[a[0]+u[0]*t,a[1]+u[1]*t],start=at(cuts[j-1]),end=at(cuts[j]);
        if(dist(start,end)<=eps)continue;
        const mid=at((cuts[j-1]+cuts[j])/2),normal=[-u[1]/len*eps,u[0]/len*eps];
        if(!inUnion([mid[0]+normal[0],mid[1]+normal[1]])||inUnion([mid[0]-normal[0],mid[1]-normal[1]]))continue;
        if(!edges.some(e=>dist(e[0],start)<eps&&dist(e[1],end)<eps))edges.push([start,end]);
      }
    }));
    if(!edges.length)return null;
    const edge=edges.shift(),outline=[edge[0],edge[1]];
    while(dist(outline[0],outline.at(-1))>eps*4){
      const next=edges.findIndex(e=>dist(e[0],outline.at(-1))<=eps*4);
      if(next<0)return null;outline.push(edges.splice(next,1)[0][1]);
    }
    if(edges.length)return null; // Disconnected shapes or ambiguous point contact.
    outline.pop();
    return outline.filter((p,i,all)=>Math.abs(cross(sub(p,all[(i+all.length-1)%all.length]),sub(all[(i+1)%all.length],p)))>eps*eps);
  },
  moveEdge(points, edge, delta, lockWidth) {
    // Move a complete edge; preserve direction and parallel connected sides.
    const out=points.map(p=>[...p]),u=[points[1][0]-points[0][0],points[1][1]-points[0][1]],len=Math.hypot(...u);
    if(!len||!Number.isFinite(delta))return null;
    const along=edge==='start'||edge==='end',axis=along?u.map(v=>v/len):[-u[1]/len,u[0]/len];
    const ids=along&&lockWidth?[0,1,2,3]:{start:[0,3],end:[1,2],top:[0,1],bottom:[3,2]}[edge];
    if(!ids)return null;
    ids.forEach(i=>{out[i][0]+=axis[0]*delta;out[i][1]+=axis[1]*delta;});
    const signs=out.map((a,i)=>{const b=out[(i+1)%4],c=out[(i+2)%4];return (b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]);});
    const oldSign=(points[1][0]-points[0][0])*(points[2][1]-points[1][1])-(points[1][1]-points[0][1])*(points[2][0]-points[1][0]);
    return signs.every(v=>v*oldSign>0&&Math.abs(v)>.1)?out:null;
  },
  cornerPairs(panels) {
    const candidates=new Map(),result=[];
    for(const p of panels){const match=p.label.trim().match(/^(P\s*\d+)\s*([ab])$/i);if(match){const key=match[1].replace(/\s/g,'').toUpperCase();if(!candidates.has(key))candidates.set(key,[]);candidates.get(key).push(p);}}
    for(const pair of candidates.values()){
      if(pair.length!==2||pair.some(p=>p.corner_group)||pair[0].label.slice(-1).toLowerCase()===pair[1].label.slice(-1).toLowerCase())continue;
      const [a,b]=pair,axis=p=>[p.points[1][0]-p.points[0][0],p.points[1][1]-p.points[0][1]],u=axis(a),v=axis(b);
      if(Math.abs(u[0]*v[0]+u[1]*v[1])/(Math.hypot(...u)*Math.hypot(...v))>.3)continue;
      const depth=Math.max(...pair.map(p=>Math.hypot(p.points[2][0]-p.points[1][0],p.points[2][1]-p.points[1][1])));
      if(Math.min(...a.points.flatMap(x=>b.points.map(y=>Math.hypot(x[0]-y[0],x[1]-y[1]))))<=depth*1.5)result.push(pair);
    }
    return result;
  },
  snap(moving,target){
    let best=null;
    for(let i=0;i<4;i++)for(let j=0;j<4;j++){
      const a=moving[i],b=moving[(i+1)%4],c=target[j],d=target[(j+1)%4];
      const u=[b[0]-a[0],b[1]-a[1]],v=[d[0]-c[0],d[1]-c[1]],lu=Math.hypot(...u),lv=Math.hypot(...v);
      if(!lu||!lv||Math.abs(u[0]*v[1]-u[1]*v[0])/(lu*lv)>1e-6)continue;
      const tangent=[v[0]/lv,v[1]/lv],normal=[-tangent[1],tangent[0]];
      const project=p=>(p[0]-c[0])*tangent[0]+(p[1]-c[1])*tangent[1];
      const low=Math.min(project(a),project(b)),high=Math.max(project(a),project(b));
      // Retain the existing position along a longer edge (especially at L corners).
      // Only shift tangentially when needed to fully overlap the shorter edge.
      const lower=lu<=lv?-low:lv-high,upper=lu<=lv?lv-high:-low;
      const along=Math.max(lower,Math.min(0,upper));
      const across=(c[0]-a[0])*normal[0]+(c[1]-a[1])*normal[1];
      const dx=along*tangent[0]+across*normal[0],dy=along*tangent[1]+across*normal[1],distance=Math.hypot(dx,dy);
      // After translation, the panels must lie on opposite sides of their shared edge.
      const center=points=>points.reduce((s,p)=>[s[0]+p[0]/4,s[1]+p[1]/4],[0,0]);
      const mc=center(moving),tc=center(target);
      const side1=v[0]*(mc[1]+dy-c[1])-v[1]*(mc[0]+dx-c[0]);
      const side2=v[0]*(tc[1]-c[1])-v[1]*(tc[0]-c[0]);
      if(side1*side2>=0)continue;
      if(!best||distance<best.distance)best={points:moving.map(p=>[p[0]+dx,p[1]+dy]),distance,edge:i,targetEdge:j};
    }
    return best;
  }
};
