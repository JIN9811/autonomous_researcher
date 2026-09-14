from agents.bo.presentation import project_bo_report


def test_bound_objective_is_available_before_bo_and_is_not_old_plot_objective():
    spec = {'objective_id': 'sea', 'version': 2, 'name': 'Specific energy absorption',
            'direction': 'maximize', 'expression': {'op': 'metric', 'metric_id': 'specific_energy_absorption_j_per_g'}}
    status = {'active_binding': {'objective_id': 'sea', 'version': 2, 'objective_hash': 'h2'},
              'objective_states': [{'objective_id': 'sea', 'version': 2, 'objective_hash': 'h2', 'spec': spec}]}
    report = project_bo_report({'_objective_status': status, '_projection_state': {'run_id': 'r'}}, {})
    objective = report['objective_display']
    assert objective['name'] == 'Specific energy absorption'
    assert objective['unit'] == 'J/g'
    assert objective['run_bound'] is True
    assert objective['run_id'] == 'r'
    assert 'specific_energy_absorption' in objective['equation']


def test_mismatched_binding_does_not_display_another_revision():
    report = project_bo_report({'_objective_status': {
        'active_binding': {'objective_id': 'sea', 'version': 2, 'objective_hash': 'h2'},
        'objective_states': [{'objective_id': 'sea', 'version': 1, 'objective_hash': 'h1', 'spec': {'name': 'Wrong'}}]}}, {})
    assert report['objective_display'] is None


def test_archive_preserves_original_plot_identity():
    original = {'name': 'Historical score', 'equation': 'objective_score', 'unit': ''}
    report = project_bo_report({'bo_agent': {'visualization': {'objective': original}}}, {})
    assert report['objective_display']['name'] == 'Historical score'
    assert original == {'name': 'Historical score', 'equation': 'objective_score', 'unit': ''}
