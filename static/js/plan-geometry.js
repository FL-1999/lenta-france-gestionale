/* Rigid edge alignment: measured widths and shape are never stretched. */
window.PlanGeometry={
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
