"""Power in the Liberty writer: left out unless asked for (results/power_validation.txt), written when asked."""

from src.cell.liberty_write import cell_group


def timing():
    t = [[0.1, 0.2], [0.1, 0.2]]
    return dict(cell="dd2_gc1__x", output="Y", inputs=["A"],
                pins={"A": dict(capacitance=0.002, rise_capacitance=0.002, fall_capacitance=0.002)},
                arcs=[dict(pin="A", sense="negative_unate", index_1=[0.01, 0.1], index_2=[0.001, 0.01],
                           tables={"cell_rise": t, "cell_fall": t, "rise_transition": t, "fall_transition": t},
                           power={"rise_power": t, "fall_power": t})],
                leakage_nw={"A": 0.01, "!A": 0.0002})


def test_power_left_out_by_default():
    text = cell_group(timing(), 3.75, "!A")
    assert "leakage_power" not in text and "internal_power" not in text and "cell_rise" in text


def test_power_written_when_asked():
    text = cell_group(timing(), 3.75, "!A", power=True)
    assert text.count("leakage_power ()") == 2 and "cell_leakage_power : 0.0051000000" in text
    assert 'rise_power ("power_outputs_1")' in text and 'fall_power ("power_outputs_1")' in text
