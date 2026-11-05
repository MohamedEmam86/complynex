"""Phase 7 ESG track (H1-H4): pure-function tests (no database)."""
import io
from datetime import date, datetime

from esg import report as REP
from phishing import authz as AUTHZ
from governance import composition as COMP


# ---------------------------------------------------------------- H1 ESG period report
def test_quadrant():
    assert REP.quadrant(4, 4) == 'priority'
    assert REP.quadrant(3, 3) == 'priority'
    assert REP.quadrant(4, 2) == 'stakeholder'
    assert REP.quadrant(2, 5) == 'business'
    assert REP.quadrant(1, 1) == 'monitor'
    assert REP.quadrant(None, 4) is None


def test_materiality_rows_order_and_unscored():
    topics = [{'id': 1, 'name': 'Water'}, {'id': 2, 'name': 'Data privacy'}, {'id': 3, 'name': 'Biodiversity'}]
    scores = {1: {'stakeholder_importance': 2, 'business_impact': 2}, 2: {'stakeholder_importance': 5, 'business_impact': 4}}
    rows = REP.materiality_rows(topics, scores)
    assert [r['id'] for r in rows] == [2, 1, 3]
    assert rows[0]['quadrant'] == 'priority' and rows[-1]['quadrant'] is None


def test_disclosure_index_na_out_of_denominator():
    items = [{'framework': 'GRI', 'ref_code': '2-1', 'status': 'complete'},
             {'framework': 'GRI', 'ref_code': '2-2', 'status': 'partial'},
             {'framework': 'GRI', 'ref_code': '2-3', 'status': 'not_applicable'},
             {'framework': 'ISSB', 'ref_code': 'S2', 'status': 'weird'}]
    idx = REP.disclosure_index(items)
    gri = [f for f in idx if f['framework'] == 'GRI'][0]
    assert gri['applicable'] == 2 and gri['done_pct'] == 75.0
    issb = [f for f in idx if f['framework'] == 'ISSB'][0]
    assert issb['counts']['not_started'] == 1 and issb['done_pct'] == 0.0


def _rep():
    pillars = [{'code': 'E', 'name': 'Environmental', 'name_ar': 'بيئي', 'weight': 1,
                'indicators': [{'id': 1, 'code': 'E1', 'name': 'Energy', 'weight': 1, 'score': 3.0, 'evidence_notes': 'x'},
                               {'id': 2, 'code': 'E2', 'name': 'Water', 'weight': 1, 'score': None}]}]
    from esg.engine import build_pillar_summary, MATURITY_LABELS
    summary = build_pillar_summary(pillars)
    mat = REP.materiality_rows([{'id': 1, 'name': 'Energy'}, {'id': 2, 'name': 'Waste'}],
                               {1: {'stakeholder_importance': 4, 'business_impact': 4}})
    idx = REP.disclosure_index([{'framework': 'GRI', 'ref_code': '302-1', 'title': 'Energy', 'status': 'not_started'}])
    return {'period': {'label': 'FY 2026', 'start_date': date(2026, 1, 1), 'end_date': date(2026, 12, 31), 'status': 'open'},
            'framework': {'name': 'Demo framework'}, 'pillars': pillars, 'summary': summary, 'materiality': mat,
            'index': idx, 'feeds': {'training': '3 hours'}, 'carbon': None,
            'completeness': REP.completeness(summary, mat, idx), 'gaps': REP.gaps(pillars, mat, idx),
            'maturity_labels': MATURITY_LABELS, 'quadrants': REP.QUADRANTS, 'status_labels': REP.STATUS_LABELS,
            'generated_at': datetime(2026, 11, 2, 10, 0)}


def test_gaps_and_completeness():
    rep = _rep()
    kinds = sorted(g['kind'] for g in rep['gaps'])
    assert kinds == ['disclosure_not_started', 'indicator', 'materiality']
    c = rep['completeness']
    assert (c['indicators_answered'], c['indicators_total']) == (1, 2)
    assert c['materiality_pct'] == 50.0 and c['disclosures_pct'] == 0.0


def test_workbook_has_every_section():
    from openpyxl import load_workbook
    buf = io.BytesIO()
    REP.workbook(_rep()).save(buf)
    buf.seek(0)
    wb = load_workbook(buf)
    assert wb.sheetnames == ['Summary', 'Pillars', 'Indicators', 'Materiality', 'Disclosure index',
                             'Framework coverage', 'Gaps', 'From other modules']
    assert wb['Indicators'].max_row == 3


def test_workbook_neutralises_formula_injection_and_strips_control_chars():
    from openpyxl import load_workbook
    rep = _rep()
    # an evidence note a user could control: a formula-injection payload with an
    # illegal control character embedded.
    rep['pillars'][0]['indicators'][0]['evidence_notes'] = '=HYPERLINK("http://evil")\x03 drop'
    buf = io.BytesIO()
    REP.workbook(rep).save(buf)
    buf.seek(0)
    ws = load_workbook(buf)['Indicators']
    cell = [c for row in ws.iter_rows() for c in row
            if isinstance(c.value, str) and 'HYPERLINK' in c.value][0]
    assert cell.data_type == 's'                 # stored as literal text, not a formula
    assert '\x03' not in cell.value              # illegal control char stripped
    assert cell.value.startswith('=HYPERLINK')   # content otherwise preserved


# ---------------------------------------------------------------- H2 phishing authorisation
GOOD = {'organisation': 'Demo Co', 'authorised_by_name': 'A. Person', 'authorised_by_title': 'CEO',
        'scope': 'All staff, coupon scenario', 'valid_from': '2026-11-01', 'valid_to': '2026-11-30',
        'allowed_domains': 'demo.example, @branch.example'}


def test_authorisation_required():
    assert [c for c, *_ in AUTHZ.problems(None, ['a@demo.example'], 0)] == ['missing']


def test_authorisation_complete_is_ok():
    assert AUTHZ.problems(GOOD, ['a@demo.example', 'b@x.branch.example'], 1, date(2026, 11, 2)) == []


def test_authorisation_rules():
    codes = lambda **kw: [c for c, *_ in AUTHZ.problems(dict(GOOD, **kw.pop('auth', {})), kw.pop('emails', ['a@demo.example']),
                                                        kw.pop('docs', 1), kw.pop('today', date(2026, 11, 2)))]
    assert codes(docs=0) == ['document']
    assert codes(today=date(2026, 12, 1)) == ['expired']
    assert codes(today=date(2026, 10, 1)) == ['not_yet']
    assert codes(emails=['a@demo.example', 'boss@other.example']) == ['out_of_scope']
    assert codes(emails=['x@notdemo.example']) == ['out_of_scope']        # suffix match needs a dot boundary
    assert codes(auth={'revoked_at': datetime(2026, 11, 2)}) == ['revoked']
    assert codes(auth={'allowed_domains': ''}) == ['domains']
    assert 'incomplete' in codes(auth={'authorised_by_title': ' '})
    assert codes(auth={'valid_to': '2026-10-01'}) == ['dates']


def test_authorisation_messages_are_translatable_and_safe():
    # runtime text (a date, an email list) is a parameter, never folded into the
    # msgid — so the message carries no bare '%' and can be shown in Arabic.
    probs = AUTHZ.problems(dict(GOOD, valid_to='2026-11-30'), ['x@other.example'], 1, date(2026, 12, 5))
    codes = [c for c, *_ in probs]
    assert 'expired' in codes and 'out_of_scope' in codes
    for item in probs:
        en, ar = AUTHZ.message(item, 'en'), AUTHZ.message(item, 'ar')
        assert en and ar and en != ar          # both languages present, distinct
        assert '%(' not in en and '%(' not in ar   # placeholders resolved, nothing left dangling
    assert '2026-11-30' in AUTHZ.message(('expired', 'expired', {'d': '2026-11-30'}), 'ar')


def test_allowed_domain_validation():
    bad = AUTHZ.invalid_domains({'gmail.com', 'outlook.com', 'localhost', '*', 'demo.example'})
    assert set(bad) == {'gmail.com', 'outlook.com', 'localhost', '*'}
    assert AUTHZ.invalid_domains({'branch.demo.example'}) == []


def test_recipient_email_validation():
    for good in ('a@demo.example', 'first.last@branch.example.com'):
        assert AUTHZ.valid_email(good)
    for bad in ('', 'noatsign.example', 'a@@b.com', 'a@b', 'two@a@b.com',
                'Name <a@b.com>', 'a;b@c.com', 'a b@c.com', 'a@b.com, c@d.com', 'x%y@c.com'):
        assert not AUTHZ.valid_email(bad), bad


def test_domains_parsing():
    assert AUTHZ.domains('A.example; @b.example\nc.example,') == {'a.example', 'b.example', 'c.example'}


# ---------------------------------------------------------------- H3 composition
def test_committee_findings():
    c = {'min_members': 3, 'min_independent_members': 2, 'requires_financial_expert': 1, 'chairman_id': 1,
         'min_meetings_per_year': 4, 'quorum_number': 2, 'charter_next_review': '2027-01-01'}
    mem = [{'member_id': 1, 'is_independent': 1, 'status': 'ACTIVE', 'skills_financial': 5},
           {'member_id': 2, 'is_independent': 0, 'status': 'ACTIVE'}]
    codes = {f['code'] for f in COMP.check_committee(c, mem, 4, date(2026, 11, 2))}
    assert codes == {'min_members', 'independence'}


def test_committee_without_requirements_has_no_rule_findings():
    mem = [{'member_id': 1, 'status': 'ACTIVE'}]
    codes = {f['code'] for f in COMP.check_committee({'chairman_id': 1, 'charter_file': 'x.pdf'}, mem, 0, date(2026, 11, 2))}
    assert codes == set()


def test_member_findings():
    f = COMP.check_members([{'status': 'ACTIVE', 'member_name': 'X', 'term_end_date': '2026-01-01',
                             'fit_proper_next_review': '2026-06-01', 'is_independent': 1},
                            {'status': 'RESIGNED', 'member_name': 'Y', 'term_end_date': '2020-01-01'}], date(2026, 11, 2))
    assert sorted(x['code'] for x in f) == ['fit_proper', 'independence_declaration', 'term_ended']
    assert all(x['message'] % x['params'] and x['message_ar'] % x['params'] for x in f)


# ---------------------------------------------------------------- H2 feed detection
def test_awareness_feed_detected():
    from esg import feeds
    assert feeds.detect('Phishing simulation click rate') == 'awareness'
    assert feeds.detect('Average hours of training per employee') == 'training'
