const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('new BO measurement overrides initial LHS snapshot',()=>{
 const source=fs.readFileSync('web/static/planning.js','utf8'), start=source.indexOf('function latestBoInitialDesign(');
 const context=vm.createContext({liveLhsVisualization:null,window:{LHSDesignVisualization:{isValid:()=>true}}});
 vm.runInContext(source.slice(start,source.indexOf('\n}',start)+2),context);
 const initial={run_id:'r',step:1,initial_design:{completed:0}};
 const measured={run_id:'r',step:2,initial_design:{completed:1}};
 const report={state:{run_id:'r',run_metadata:{lhs_visualization:initial,bo_agent:{lhs_visualization:measured}}}};
 assert.equal(context.latestBoInitialDesign(report).completed,1);
 report.state.run_metadata.bo_agent.lhs_visualization={...measured,run_id:'old'};
 assert.equal(context.latestBoInitialDesign(report).completed,0);
});
