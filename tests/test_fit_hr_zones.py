"""Zone cardiache dei FIT di corsa: arrotondamento, confini, pause, buchi."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fit_hr_zones as z  # noqa: E402

EDGES = z.zone_edges(204)


def test_edges_for_204_round_half_up():
    assert EDGES == [102, 122, 143, 163, 184, 204]


def test_edge_round_half_up_not_bankers():
    assert z.zone_edges(205, (50,)) == [103]  # 102.5 -> 103


@pytest.mark.parametrize("hr,slot", [(101, 0), (102, 1), (121, 1), (122, 2), (142, 2),
                                     (143, 3), (162, 3), (163, 4), (183, 4), (184, 5),
                                     (203, 5), (204, 6), (230, 6)])
def test_boundary_value_goes_to_upper_zone(hr, slot):
    assert z.zone_slot(hr, EDGES) == slot


def samples(rows):
    return z.clean_samples([{"timestamp": t, "heart_rate": h} for t, h in rows])


def test_time_weighting_uses_timestamps_not_sample_count():
    s = samples([(0, 130), (1, 130), (9, 170), (10, 170)])  # 1 s, 8 s, 1 s di intervallo
    zt = z.zone_time(s, EDGES, (0, 10), [(0, 10)])
    assert zt.slots[2] == 9 and zt.slots[4] == 1 and zt.classified_s == 10  # il 130 vale 9 s


def test_gap_over_limit_is_unclassifiable_not_invented():
    s = samples([(0, 130), (60, 130), (61, 130)])
    zt = z.zone_time(s, EDGES, (0, 61), [(0, 61)])
    assert zt.unclassifiable_s == 60 and zt.slots[2] == 1


def test_missing_hr_is_unclassifiable_never_zero_zone():
    s = samples([(0, 130), (1, None), (2, 130), (3, 130)])
    zt = z.zone_time(s, EDGES, (0, 3), [(0, 3)])
    assert zt.slots[0] == 0 and zt.unclassifiable_s == 1 and zt.slots[2] == 2


def test_paused_timer_time_is_excluded():
    s = samples([(0, 130), (1, 130), (2, 130), (3, 130), (4, 130), (5, 130)])
    zt = z.zone_time(s, EDGES, (0, 5), [(0, 2), (4, 5)])  # pausa tra 2 e 4
    assert zt.classified_s == 3


def test_duplicate_timestamps_keep_first_and_are_counted():
    s = samples([(0, 130), (0, 190), (1, 130)])
    assert s.anomalies["duplicate_timestamps"] == 1 and s.hr[0] == 130


def test_window_clips_segment():
    s = samples([(i, 150) for i in range(11)])
    zt = z.zone_time(s, EDGES, (2.5, 6), [(0, 10)])
    assert zt.slots[3] == pytest.approx(3.5)


def test_running_periods_from_events():
    ev = [{"event": "timer", "event_type": "start", "timestamp": 0},
          {"event": "timer", "event_type": "stop_all", "timestamp": 5},
          {"event": "timer", "event_type": "start", "timestamp": 8}]
    assert z.running_periods(ev, 0, 20) == [(0, 5), (8, 20)]


def test_fit_crc_known_value():
    assert z.fit_crc(b"") == 0
    assert z.fit_crc(b"123456789") == 0xBB3D  # CRC-16/ARC


SAMPLE = Path(__file__).resolve().parents[1] / "data/fit-hr-zones/original_backup/25006802709.fit"


@pytest.mark.skipif(not SAMPLE.exists(), reason="FIT di prova non presente")
def test_end_to_end_only_authorized_bytes_change(tmp_path):
    pytest.importorskip("garmin_fit_sdk")
    out, ok = z.process(SAMPLE, tmp_path / "o", tmp_path / "r", 204)
    assert ok and out.exists()
    a, b = SAMPLE.read_bytes(), out.read_bytes()
    assert len(a) == len(b) and a != b
    with pytest.raises(FileExistsError):
        z.process(SAMPLE, tmp_path / "o", tmp_path / "r", 204)
