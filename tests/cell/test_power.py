"""Power in the Liberty writer: written where it was measured, left out where it was not, or when asked."""

from src.cell.liberty_write import cell_group


def timing():
    t = [[0.1, 0.2], [0.1, 0.2]]
    return dict(cell="dd2_gc1__x", output="Y", inputs=["A"],
                pins={"A": dict(capacitance=0.002, rise_capacitance=0.002, fall_capacitance=0.002)},
                arcs=[dict(pin="A", sense="negative_unate", index_1=[0.01, 0.1], index_2=[0.001, 0.01],
                           tables={"cell_rise": t, "cell_fall": t, "rise_transition": t, "fall_transition": t},
                           power={"rise_power": t, "fall_power": t})],
                leakage_nw={"A": 0.01, "!A": 0.0002})


def test_power_left_out_where_not_measured():
    t = timing()
    del t["leakage_nw"]
    for arc in t["arcs"]:
        del arc["power"]
    text = cell_group(t, 3.75, "!A")
    assert "leakage_power" not in text and "internal_power" not in text and "cell_rise" in text
    assert "internal_power" not in cell_group(timing(), 3.75, "!A", power=False)


def test_power_written_where_measured():
    text = cell_group(timing(), 3.75, "!A")
    assert text.count("leakage_power ()") == 2 and "cell_leakage_power : 0.0051000000" in text
    assert 'rise_power ("power_outputs_1")' in text and 'fall_power ("power_outputs_1")' in text
