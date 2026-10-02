"""Explicit numerical entry points; never submit an AgentContext or device registry."""
def execute(job, payload):
    if job.startswith('geometry.'):
        from mcp_tools.mock_tools import _generate_geometry_stl, _check_mesh_quality, _check_manufacturability
        functions = {'geometry.generate': _generate_geometry_stl,
                     'geometry.quality': _check_mesh_quality,
                     'geometry.manufacturability': _check_manufacturability}
        if job not in functions:
            raise ValueError('Unknown geometry CPU job')
        return functions[job](payload)
    if job == 'analysis.read_curve':
        from agents.analysis.agent import AnalysisAgent
        return AnalysisAgent()._curve_from_equipment(payload)
    if job == 'analysis.metrics':
        from agents.analysis.agent import AnalysisAgent
        agent = AnalysisAgent()
        return {'stress_strain_curve': agent._stress_strain_curve(payload['curve'], payload['geometry']),
                'metrics': agent._metrics(payload['curve'], payload['geometry'])}
    if job == 'bo.propose':
        import torch
        torch.set_num_threads(1)
        from learning.botorch_backend import propose_next
        from learning.bo_parameter_space import BOParameterSpace
        payload = dict(payload)
        payload['parameter_space'] = BOParameterSpace.from_mapping(payload['parameter_space'])
        return propose_next(**payload).to_dict()
    if job == 'bo.render':
        from reporting.bo_visualization_artifacts import write_bo_visualization_artifacts
        return write_bo_visualization_artifacts(payload['payload'], payload['output_dir'])
    raise ValueError(f'Not a CPU-only job: {job}')
