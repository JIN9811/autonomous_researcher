"""Exercise the real IDE tab/navigation functions without activating a graph."""
from pathlib import Path
import subprocess

from test_planning_design_report_js import _extract_function


def test_bridge_navigation_uses_one_tab_and_preserves_graph_module_and_trace():
    source = (Path(__file__).resolve().parents[2] / "web/static/runtime_ide.js").read_text()
    functions = "\n".join(_extract_function(source, name) for name in (
        "activeGraphTab", "rememberActiveGraphDraft", "upsertGraphTab", "normalizeGraphTabId",
        "activateGraphTab", "closeGraphTab", "currentExperimentalPackageGraph",
        "openPackageCompositionView", "closePackageCompositionView", "focusModuleForNode", "selectNode", "openDeviceBridgeInternal",
    ))
    script = """
const assert = require('node:assert/strict');
const MAIN_GRAPH_TAB_ID='main-system', MODULE_TAB_PREFIX='module:', BRIDGE_GRAPH_TAB_ID='infra:device-bridges', PACKAGE_MANAGER_TAB_ID='infra:package-manager';
const main={id:'main',nodes:[{id:'bridges',kind:'bridge',module_id:null}]};
const moduleGraph={id:'module:specimen',nodes:[],metadata:{ide_tab_kind:'module'}};
let graphTabs=[{id:MAIN_GRAPH_TAB_ID,kind:'main',fixed:true,graph:main,dirty:true},
  {id:'module:specimen',kind:'module',moduleId:'specimen',graph:moduleGraph,dirty:true}];
let activeGraphTabId=MAIN_GRAPH_TAB_ID, activeGraph=main, selectedNodeId='bridges';
let canvasAutoSelectNode=true,activeRuntimeEdge=null,edgeConnectDraft=null,edgeConnectSource='',edgeConnectMode=false;
let activeModuleId='',moduleOpenToken=null;
const moduleSelect=null,modulePayloadCache=new Map();
const graphJson={value:JSON.stringify(main)};
const dryRunOutput={innerHTML:'previous trace',dataset:{},scrollIntoView(){}};
const packageCompositionOutput={scrollIntoView(){}};
const graphTabsOutput={scrollIntoView(){}};
let moduleCollections=0;
const collectExperimentalModuleConfigurations=()=>{moduleCollections++;};
let packageCompositionReturnMarkup='',packageCompositionNotice=null;
const cloneConfig=value=>JSON.parse(JSON.stringify(value));
const parseGraphEditor=()=>JSON.parse(graphJson.value);
const findNodeById=id=>activeGraph.nodes.find(node=>node.id===id);
const renderGraphTabs=()=>{};
const showRuntimeEquipmentFlowWorkspace=()=>{};
const showPackageCompositionWorkspace=()=>{};
let packageRenders=0;
const renderPackageComposition=()=>{packageRenders++;};
const renderDeviceBridges=()=>{const graph={id:'projection',metadata:{read_only:true},nodes:[{id:'bridge:fleet',kind:'bridge',label:'Fleet',metadata:{bridge_id:'fleet'}}]};renderGraph(graph);};
const requestAnimationFrame=callback=>callback();
const focusGraphNodeInCanvas=()=>{};
const renderGraph=graph=>{activeGraph=graph;graphJson.value=JSON.stringify(graph);activeGraphTab().graph=graph;};
""" + functions + """
// A bridge has no agent module_id; both node gestures must still enter its tab.
focusModuleForNode('bridges');
assert.equal(activeGraphTabId,BRIDGE_GRAPH_TAB_ID);
assert.equal(activeGraphTab().kind,'bridges');
assert.equal(dryRunOutput.innerHTML,'previous trace');
assert.deepEqual(currentExperimentalPackageGraph(),main);
openPackageCompositionView('bridges');
assert.equal(graphTabs.filter(tab=>tab.kind==='bridges').length,1);
assert.equal(activeGraphTab().graph.metadata.read_only,true);
selectNode('bridge:fleet');
assert.equal(activeGraphTabId,BRIDGE_GRAPH_TAB_ID,'Single click selects; it must not leave the plane');
focusModuleForNode('bridge:fleet');
assert.equal(activeGraphTabId,'infra:bridge:fleet');
closePackageCompositionView();
assert.equal(activeGraphTabId,BRIDGE_GRAPH_TAB_ID);
closePackageCompositionView();
assert.equal(activeGraphTabId,MAIN_GRAPH_TAB_ID);
selectNode('bridges');
assert.equal(activeGraphTabId,BRIDGE_GRAPH_TAB_ID);
activateGraphTab('module:specimen');
const edited={...moduleGraph,description:'unsaved edit'};
graphJson.value=JSON.stringify(edited);
openPackageCompositionView('bridges');
assert.deepEqual(graphTabs.find(tab=>tab.id==='module:specimen').graph,edited);
assert.equal(moduleCollections,1);
assert.deepEqual(currentExperimentalPackageGraph(),main);
closeGraphTab(BRIDGE_GRAPH_TAB_ID);
assert.equal(activeGraphTabId,'module:specimen');
assert.deepEqual(activeGraph,edited);
assert.equal(graphTabs.find(tab=>tab.id==='module:specimen').dirty,true);
assert.equal(dryRunOutput.innerHTML,'previous trace');
assert.equal(graphTabs.some(tab=>tab.id===BRIDGE_GRAPH_TAB_ID),false);
// Package management is a different view, not the bridge topology.
openPackageCompositionView();
assert.equal(activeGraphTabId,PACKAGE_MANAGER_TAB_ID);
assert.equal(activeGraphTab().kind,'packages');
assert.equal(activeGraphTab().graph,undefined);
assert.deepEqual(currentExperimentalPackageGraph(),main);
openPackageCompositionView('bridges');
assert.equal(activeGraphTabId,BRIDGE_GRAPH_TAB_ID);
assert.equal(graphTabs.filter(tab=>tab.kind==='packages').length,1);
closePackageCompositionView();
assert.equal(activeGraphTabId,'module:specimen');
// Closing a module must actually render its preceding auxiliary tab.
const specimenTab=graphTabs.find(tab=>tab.id==='module:specimen');
const packageTab=graphTabs.find(tab=>tab.id===PACKAGE_MANAGER_TAB_ID);
graphTabs=[graphTabs[0],packageTab,specimenTab];
const renderedBeforeClose=packageRenders;
closeGraphTab('module:specimen');
assert.equal(activeGraphTabId,PACKAGE_MANAGER_TAB_ID);
assert.equal(packageRenders,renderedBeforeClose+1);
assert.deepEqual(currentExperimentalPackageGraph(),main);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
