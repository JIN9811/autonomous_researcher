from app.controller import MainController


def test_display_keeps_existing_peak_preserving_samples():
    rows = [{"source_row_index": i, "strain": i / 400, "stress_MPa": 1.0} for i in range(180)]
    rows[3]["stress_MPa"] = 10.0
    rows[4]["stress_MPa"] = 0.0
    result = MainController._planning_display_analysis({"stress_strain_curve": {"preview": rows}})
    preview = result["stress_strain_curve"]["preview"]
    assert len(preview) == 180
    assert preview[3]["stress_MPa"] == 10.0
    assert preview[4]["stress_MPa"] == 0.0
