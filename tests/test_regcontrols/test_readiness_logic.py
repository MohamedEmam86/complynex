"""Unit tests for regcontrols.readiness_logic."""
from datetime import date

from regcontrols import readiness_logic as RL


def c(st, crit='medium', area='a', code='X'):
    return {'last_status': st, 'criticality': crit, 'area': area, 'control_code': code}


def test_weighted_score():
    # critical pass (4 x 100) + low fail (1 x 0) + high warning (3 x 50) = 550 / 8 = 68.8
    s = RL.score([c('pass', 'critical'), c('fail', 'low'), c('warning', 'high')])
    assert s['score'] == 68.8 and s['failing'] == 1 and s['controls'] == 3


def test_not_applicable_excluded_and_unassessed_counted():
    s = RL.score([c('pass'), c('not_applicable'), c(None)])
    assert s['controls'] == 2 and s['score'] == 50.0 and s['not_assessed'] == 1


def test_bands_and_areas():
    assert RL.band(90) == 'ready' and RL.band(70) == 'partial' and RL.band(10) == 'not_ready' and RL.band(None) == 'none'
    areas = RL.by_area([c('pass', area='x'), c('fail', area='y')])
    assert areas['x']['score'] == 100 and areas['y']['score'] == 0


def test_top_gaps_critical_first():
    gaps = RL.top_gaps([c('fail', 'low', code='L'), c('warning', 'critical', code='C'), c('pass', 'critical', code='P')])
    assert [g['control_code'] for g in gaps] == ['C', 'L']


def test_occurrences():
    q = RL.occurrences('quarterly', 15, 1, date(2026, 1, 1), date(2026, 12, 31))
    assert q == [date(2026, 1, 15), date(2026, 4, 15), date(2026, 7, 15), date(2026, 10, 15)]
    m = RL.occurrences('monthly', 31, None, date(2026, 2, 1), date(2026, 3, 31))
    assert m == [date(2026, 2, 28), date(2026, 3, 31)]
    assert RL.occurrences('annual', 30, 4, date(2026, 1, 1), date(2027, 12, 31)) == [date(2026, 4, 30), date(2027, 4, 30)]
    assert len(RL.occurrences('weekly', 0, None, date(2026, 10, 1), date(2026, 10, 31))) == 4
    assert RL.occurrences('adhoc') == []


def test_reminders():
    t = date(2026, 10, 1)
    assert RL.reminders_due(date(2026, 10, 12), t, [14, 3, 0]) == [14]
    assert RL.reminders_due(date(2026, 10, 3), t, [14, 3, 0], already=[14]) == [3]
    assert RL.reminders_due(date(2026, 10, 1), t, [14, 3, 0], already=[14, 3]) == [0]
    assert RL.reminders_due(date(2026, 12, 1), t, [14, 3, 0]) == []
