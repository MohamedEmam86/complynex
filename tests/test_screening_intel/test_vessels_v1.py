"""Vessel screening V1-V3: identifiers, names, the four layers, merging, whitelist, flags and the list
handlers' ship data. The DB-backed part at the end runs only with VESSELS_TEST_DB=<a scratch database with
the vessel migration and real lists loaded> (skipped otherwise)."""
import json
import os

import pytest

from screening import vessel_utils as VU
from screening import vessel_engine as VE
from screening.format_handlers import OFACHandler, HMTreasuryHandler, EUSanctionsHandler, OpenSanctionsHandler


def test_imo_check_digit_and_normalisation():
    assert VU.imo_valid('9074729') and VU.imo_valid('IMO 9074729') and VU.imo_valid('IMO: 9074729')
    assert not VU.imo_valid('9074728') and not VU.imo_valid('907472')
    assert VU.norm_imo('IMO٩٠٧٤٧٢٩') == '9074729'
    assert VU.mmsi_valid('273111111') and not VU.mmsi_valid('973111111') and not VU.mmsi_valid('27311111')


def test_name_normalisation_and_numbers():
    assert VU.norm_name('M/V "Ocean Star-1"') == 'OCEAN STAR 1'
    assert VU.norm_name('MT OCEANSTAR1') == 'OCEANSTAR 1'
    assert VU.name_numbers(VU.norm_name('STAR II')) == (2,)
    assert VU.name_numbers(VU.norm_name('STAR I')) == (1,)        # a trailing lone I / V / X is a hull number
    assert VU.name_numbers(VU.norm_name('PROGRESS V')) == (5,) and VU.norm_name('PROGRESS V') == 'PROGRESS V'
    assert VU.name_numbers(VU.norm_name('I AM STAR')) == ()       # elsewhere it stays a letter


def _c(wid, name, imo=None, **kw):
    d = dict(watchlist_id=wid, group_key=kw.pop('group', ('IMO:' + imo) if imo and VU.imo_valid(imo) else 'WL:%d' % wid),
             source=kw.pop('source', 'ofac'), parties=kw.pop('parties', []), risk_score=0, list_type='SANCTIONS', name=name, names=[name] + kw.pop('alt', []),
             previous_names=kw.pop('prev', []), imo=imo, mmsi=kw.pop('mmsi', None), call_sign=None,
             flag=kw.pop('flag', None), flags_past=kw.pop('flags_past', []), type=None, year_built=None,
             measures=['asset_freeze'], owners=[], gross_tonnage=None, legal_status=None)
    d['names'] += d['previous_names']
    return d


CANDS = [_c(1, 'OCEAN STAR 1', '9074729', prev=['SEA PEARL'], mmsi='273111111', flag='Panama',
            flags_past=['Togo', 'Cameroon']),
         _c(2, 'OCEAN STAR 2', '9074731'),
         _c(3, 'AL NOUR', alt=['النور']),
         _c(4, 'OCEAN GLORY', '9387425'),
         _c(5, 'OCEAN STAR 1', '9074729', source='hmt', flag='Panama'),            # same ship, another list
         _c(6, 'ATTICA STAR', '9436941', alt=['ATTICA'], parties=[{'name': 'Acme Shipping LLC', 'role': 'owner', 'party_listed': True}]),
         _c(7, 'UTAKI', '9262924'), _c(8, 'YATEEKA', '9191553')]
IDX = {('IMO', '9074729'): [(1, True), (5, True)], ('IMO', '9074731'): [(2, True)], ('MMSI', '273111111'): [(1, True)],
       ('IMO', '9387425'): [(4, False)]}


FLAGS = {'panama': {'foc': True, 'high_risk': False}, 'iran': {'foc': False, 'high_risk': True}}


def run(**kw):
    kw.setdefault('whitelist', {})
    return VE.screen_vessel(candidates=CANDS, id_index=IDX, flags=FLAGS, links={}, **kw)


def codes(items):
    return [i['code'] for i in items]


def test_imo_confirms_even_after_renaming():
    r = run(name='SOMETHING ELSE', imo='IMO 9074729')
    assert r['tier'] == 'CONFIRMED' and r['hits'][0]['watchlist_id'] == 1
    assert 'renamed' in codes(r['hits'][0]['explanation'])
    h = r['hits'][0]
    assert sorted(h['sources']) == ['hmt', 'ofac'] and len(r['hits']) == 1       # one ship, two lists
    assert 'several_lists' in codes(h['explanation'])
    assert all(e['en'] and e['ar'] for e in h['explanation'])                   # bilingual


def test_former_imo_still_confirms():
    r = run(imo='9387425')
    assert r['hits'][0]['watchlist_id'] == 4 and r['tier'] == 'CONFIRMED'
    assert r['hits'][0]['explanation'][0]['p']['when'] == 'former'


def test_name_alone_never_confirms_and_prefixes_ignored():
    r = run(name='mv ocean star-1')
    assert r['tier'] == 'POTENTIAL' and r['hits'][0]['watchlist_id'] == 1


def test_numbers_must_match():
    r = run(name='OCEAN STAR 3')
    assert r['tier'] == 'CLEAR' and not r['hits']
    r = run(name='OCEAN STAR 2')
    assert [h['watchlist_id'] for h in r['hits']] == [2]


def test_different_valid_imo_is_another_ship():
    r = run(name='OCEAN GLORY', imo='9074729')     # name of ship 4, IMO of ship 1
    tops = {h['group_key']: h for h in r['hits']}
    assert 'IMO:9074729' in tops and tops['IMO:9074729']['tier'] == 'CONFIRMED'
    assert 'IMO:9387425' not in tops                 # same name, different IMO: below threshold
    assert any(n['name'] == 'OCEAN GLORY' for n in r['near'])


def test_former_name_and_typo():
    r = run(name='SEA PERL')
    assert r['hits'] and r['hits'][0]['watchlist_id'] == 1 and r['tier'] in ('POTENTIAL', 'LOW')


def test_single_common_word_is_not_a_hit():
    assert run(name='OCEAN')['tier'] == 'CLEAR'
    assert run(name='STAR')['tier'] == 'CLEAR'


def test_arabic_name_finds_the_ship():
    r = run(name='النور')
    assert r['hits'] and r['hits'][0]['watchlist_id'] == 3


def test_mmsi_alone_is_potential_not_confirmed():
    r = run(mmsi='273111111')
    assert r['tier'] == 'POTENTIAL'


def test_risk_lines_never_create_a_match():
    r = run(name='UNKNOWN VESSEL XYZ', imo='9074728', flag='Panama')
    # 9074728 fails its check digit and is one keying error from the listed 9074729: review, never a match
    assert VE.decision(r)[0] == 'review' and 'near_imo' in codes(r['hits'][0]['explanation'])
    assert r['risk']['score'] > 0
    assert {'r_invalid_imo', 'r_foc'} <= set(codes(r['risk']['lines']))
    r = run(name='UNKNOWN VESSEL XYZ', flag='Iran', flags_past='Togo; Comoros; Panama')
    assert r['tier'] == 'CLEAR' and {'r_high_risk_flag', 'r_flag_changes'} <= set(codes(r['risk']['lines']))


def test_owner_layer():
    r = run(name='NO SUCH SHIP', owner='Acme Shipping',
            screen_party=lambda n: [{'name': 'ACME SHIPPING LLC', 'score': 92.0, 'list_type': 'SANCTIONS'}])
    assert r['owner_hits'] and r['tier'] in ('POTENTIAL', 'CONFIRMED')


def test_nothing_to_screen():
    assert run()['tier'] == 'INCOMPLETE'


# ---------------------------------------------------------------- handlers
OFAC_XML = b"""<?xml version="1.0"?><sdnList xmlns="urn:x"><sdnEntry><uid>1</uid><lastName>OCEAN STAR</lastName>
<sdnType>Vessel</sdnType><programList><program>X</program></programList>
<idList><id><idType>Vessel Registration Identification</idType><idNumber>IMO 9074729</idNumber></id>
<id><idType>MMSI</idType><idNumber>273111111</idNumber></id><id><idType>Former Vessel Flag</idType><idNumber>Togo</idNumber></id></idList>
<vesselInfo><callSign>UBCD</callSign><vesselType>Crude Oil Tanker</vesselType><vesselFlag>Panama</vesselFlag></vesselInfo>
<remarks>(Linked To: ACME SHIPPING LLC)</remarks></sdnEntry></sdnList>"""


def test_ofac_vessel_block():
    e = OFACHandler().parse(OFAC_XML)[0]
    v = e['properties']['vessel']
    assert e['entity_type'] == 'VESSEL'
    assert v['imo'] == '9074729' and v['mmsi'] == ['273111111'] and v['call_sign'] == ['UBCD']
    assert v['flag'] == 'Panama' and v['flags_past'] == ['Togo'] and v['owners'][0]['name'] == 'ACME SHIPPING LLC'


UK_XML = b"""<?xml version="1.0"?><Designations><Designation><UniqueID>RUS1</UniqueID>
<Names><Name><Name6>SEA PEARL</Name6><NameType>Primary Name</NameType></Name></Names>
<IndividualEntityShip>Ship</IndividualEntityShip><SanctionsImposed>Asset freeze|Prohibition of port entry</SanctionsImposed>
<ShipDetails><Ship><IMONumbers><IMONumber>IMO9074729</IMONumber></IMONumbers>
<CurrentOwnerOperators><CurrentOwnerOperator>Acme Shipping</CurrentOwnerOperator></CurrentOwnerOperators>
<CurrentBelievedFlagOfShips><CurrentBelievedFlagOfShip>Comoros</CurrentBelievedFlagOfShip></CurrentBelievedFlagOfShips>
<PreviousFlags><PreviousFlag>India</PreviousFlag></PreviousFlags><TypeOfShipDetails><TypeOfShip>Tanker</TypeOfShip></TypeOfShipDetails>
<YearsBuilt><YearBuilt>2001</YearBuilt></YearsBuilt></Ship></ShipDetails></Designation></Designations>"""


def test_uk_ship_block():
    e = HMTreasuryHandler().parse(UK_XML)[0]
    v = e['properties']['vessel']
    assert e['entity_type'] == 'VESSEL' and v['imo'] == '9074729' and v['flag'] == 'Comoros'
    assert v['flags_past'] == ['India'] and v['year_built'] == '2001'
    assert set(v['measures']) == {'asset_freeze', 'port_ban'}


def test_opensanctions_vessel_in_both_modes():
    line = json.dumps({'id': 'v1', 'schema': 'Vessel', 'caption': 'OCEAN STAR', 'datasets': ['x'],
                       'properties': {'name': ['OCEAN STAR'], 'imoNumber': ['9074729'], 'mmsi': ['273111111'],
                                      'flag': ['pa'], 'pastNames': ['SEA PEARL'], 'topics': ['sanction'],
                                      'owner': ['o1']}})
    from screening.format_handlers import expand_rich
    for rich in (False, True):          # ships always get their profile, whatever the OpenSanctions mode
        e = expand_rich(OpenSanctionsHandler(rich=rich)._parse_line(line))
        v = e['properties']['vessel']
        assert e['entity_type'] == 'VESSEL' and v['imo'] == '9074729' and 'SEA PEARL' in e['aliases']
        assert v['flag'] == 'Panama' and e.get('_rich')


def test_opensanctions_ownership_and_former_name_in_caption():
    h = OpenSanctionsHandler(rich=False)
    lines = [json.dumps({'id': 'v2', 'schema': 'Vessel', 'caption': 'YI MENG SHAN (formerly ATTICA)', 'datasets': ['x'],
                         'properties': {'name': ['YI MENG SHAN (formerly ATTICA)'], 'imoNumber': ['IMO9436941'],
                                        'previousName': ['Attica II'], 'flag': ['ga'], 'pastFlags': ['mt', 'pa'],
                                        'topics': ['sanction']}}),
             json.dumps({'id': 'own1', 'schema': 'Ownership', 'properties': {'owner': ['c1'], 'asset': ['v2'],
                                                                             'role': ['Owned or Controlled By']}})]
    ents = [e for e in (h._parse_line(l) for l in lines) if e]
    assert h.attach_vessel_links(ents) == 1
    from screening.format_handlers import expand_rich
    e = expand_rich(ents[0])
    v = e['properties']['vessel']
    assert e['full_name'] == 'YI MENG SHAN' and set(v['names_past']) >= {'Attica II', 'ATTICA'}
    assert v['flag'] == 'Gabon' and v['flags_past'] == ['Malta', 'Panama']
    assert v['owners'] == [{'name': None, 'role': 'owner', 'ref': 'OS-c1'}]


def test_ofac_former_names_are_kept():
    xml = OFAC_XML.replace(b'<remarks>', b'<akaList><aka><type>f.k.a.</type><category>weak</category>'
                                         b'<lastName>SEA PEARL</lastName></aka></akaList><remarks>')
    v = OFACHandler().parse(xml)[0]['properties']['vessel']
    assert v['names_past'] == ['SEA PEARL']


UN_XML = '''<?xml version="1.0" encoding="UTF-8"?><CONSOLIDATED_LIST><ENTITIES>
<ENTITY><DATAID>1</DATAID><FIRST_NAME>AVAX</FIRST_NAME><REFERENCE_NUMBER>LYe.006</REFERENCE_NUMBER>
<COMMENTS1>IMO: 9058713 Listed pursuant to resolution 2146. Flag State: Cameroon. The vessel was located near Benghazi.</COMMENTS1></ENTITY>
<ENTITY><DATAID>2</DATAID><FIRST_NAME>KOREA ACHIM SHIPPING CO</FIRST_NAME><REFERENCE_NUMBER>KPe.061</REFERENCE_NUMBER>
<COMMENTS1>Registered owner of DPRK tanker CHON MA SAN. IMO number: 5936312.</COMMENTS1></ENTITY>
</ENTITIES></CONSOLIDATED_LIST>'''.encode('utf-8')


def test_un_ships_told_apart_from_shipping_companies():
    from screening.format_handlers import UNSecurityCouncilHandler
    ents = {e['full_name']: e for e in UNSecurityCouncilHandler().parse(UN_XML)}
    assert ents['AVAX']['entity_type'] == 'VESSEL'
    v = ents['AVAX']['details']['vessel']
    assert v['imo'] == '9058713' and v['flag'] == 'Cameroon'
    assert ents['KOREA ACHIM SHIPPING CO']['entity_type'] == 'ENTITY'       # IMO company number, not a ship


def test_invalid_imo_is_kept_and_flagged():
    from screening.format_handlers import vessel_block
    from screening import vessel_store as VS
    b = vessel_block(imos=['IMO 9074728', '12345'])
    assert b['imo'] == '9074728' and b['bad_identifiers'] == ['12345']
    prof, ids = VS._profile_values(1, 'x', b)
    assert prof['imo'] == '9074728' and prof['imo_valid'] is False and ids[0][4] is False
    assert prof['group_key'] == 'WL:1'          # an invalid IMO never merges two records


def test_flags_normalised():
    from screening import vessel_flags as VF
    assert VU.clean_flag('ga') == 'Gabon' and VU.clean_flag('Korea, North') == 'North Korea'
    assert VU.clean_flag('St Kitts & Nevis') == 'Saint Kitts and Nevis' and VU.clean_flag('بنما') == 'Panama'
    assert VU.clean_flag('Unknown') is None and VU.clean_flag('None Identified') is None
    assert VU.clean_flag('Botswana False') == 'Botswana (false flag)'
    assert VF.name('Panama', 'ar') == 'بنما'


def test_arabic_prefixes_and_digits():
    assert VU.norm_name('م/ن النور ٢') == 'النور 2'
    assert VU.norm_name('ناقلة النفط أدريان داريا 1') == 'ادريان داريا 1'
    assert VU.norm_name('Mv.Pan Hope') == 'PAN HOPE'


def test_cross_script_vowels_keep_lookalikes_apart():
    r = run(name='أتيكا')
    assert r['hits'] and r['hits'][0]['imo'] == '9436941'          # matched its alias ATTICA
    assert not any(h['name'] in ('UTAKI', 'YATEEKA') for h in r['hits'])
    assert not any(h['name'] in ('UTAKI', 'YATEEKA') for h in run(name='ATTICA')['hits'])


def test_mmsi_and_name_confirm():
    r = run(mmsi='273111111', name='M/V Ocean Star 1')
    assert r['tier'] == 'CONFIRMED'


def test_declared_owner_supports_a_name_hit_but_never_confirms():
    r = run(name='ATTICA STAR', owner='ACME SHIPPING LLC')
    h = r['hits'][0]
    assert 'same_owner' in codes(h['explanation']) and 'owner_listed' in codes(h['explanation'])
    assert h['tier'] == 'POTENTIAL' and h['score'] <= VE.DEFAULTS['name_hit_max']


def test_whitelist_suppresses_until_something_changes():
    from screening import vessel_store as VS
    first = run(name='ATTICA', flag='Gabon')
    h = first['hits'][0]
    wl = {h['listed_key']: {'id': 1, 'status': 'active', 'listed_fp': h['listed_fp'], 'query_fp': first['query_fp'],
                            'by_name': 'A', 'created_at': '2026-11-18', 'reason': 'name_only'}}
    again = run(name='ATTICA', flag='Gabon', whitelist=wl)
    assert again['tier'] == 'CLEAR' and again['suppressed'][0]['listed_key'] == h['listed_key']
    wl[h['listed_key']]['listed_fp'] = 'x' * 40            # the listed ship changed since
    re1 = run(name='ATTICA', flag='Gabon', whitelist=wl)
    assert re1['hits'] and re1['hits'][0]['reopened']
    wl[h['listed_key']]['listed_fp'] = h['listed_fp']
    re2 = run(name='ATTICA', flag='Gabon', owner='Other Owner Ltd', whitelist=wl)   # screened ship changed
    assert re2['hits'] and re2['hits'][0]['reopened']
    assert VS.query_fingerprint({'name': 'ATTICA', 'flag': 'ga'}) == VS.query_fingerprint({'name': 'attica', 'flag': 'Gabon'})


def test_weights_configurable():
    r = run(name='OCEAN STAR 2', config_override={'name_weight': 0.7})
    assert r['tier'] == 'CLEAR'            # 100 * 0.7 = 70, below the LOW threshold
    assert VE.config(None, {'risk': {'foc': 99}, 'nope': 1})['risk']['foc'] == 99


def test_source_names_only_for_superadmin():
    from screening import vessel_store as VS

    class U:
        is_authenticated = True

        def __init__(self, role):
            self.role = role
    assert VS.list_label('ofac', user=U('admin')) == VS.GENERIC_LIST_LABEL
    assert VS.list_label('ofac', 'ar', user=U('compliance_officer')) == VS.GENERIC_LIST_LABEL_AR
    assert VS.list_label('ofac', user=U('superadmin')) == 'ofac'


def test_api_view_never_names_a_list():
    from api.vessels_v1 import _view
    r = run(name='SOMETHING', imo='9074729', owner='x',
            screen_party=lambda n: [{'name': 'ACME', 'score': 90.0, 'source': 'ofac'}])
    body = json.dumps(_view(1, r, 'ref'))
    assert 'ofac' not in body and 'hmt' not in body and 'International approved lists' in body


def test_people_and_companies_unchanged():
    xml = OFAC_XML.replace(b'<sdnType>Vessel</sdnType>', b'<sdnType>Entity</sdnType>')
    e = OFACHandler().parse(xml)[0]
    assert e['entity_type'] == 'ENTITY' and 'vessel' not in e['properties']


# ---------------------------------------------------------------- DB-backed (real lists loaded)
DBNAME = os.environ.get('VESSELS_TEST_DB', '')
needs_db = pytest.mark.skipif(not DBNAME, reason='needs VESSELS_TEST_DB=<scratch database with real lists>')


@pytest.fixture(scope='module')
def conn():
    import psycopg2
    import psycopg2.extras
    from config import Config
    cfg = dict(Config.POSTGRES_CONFIG, dbname=DBNAME)
    cfg.pop('database', None)
    c = psycopg2.connect(**cfg, cursor_factory=psycopg2.extras.RealDictCursor)
    yield c
    c.close()


@needs_db
def test_db_sync_is_idempotent(conn):
    from screening import vessel_store as VS
    a = VS.sync(conn)
    b = VS.sync(conn)
    assert a['vessels'] == b['vessels'] > 1000 and a['identifiers'] == b['identifiers']
    assert a['imo_check_fails'] == 0 or a['imo_check_fails'] < a['vessels'] * 0.01


@needs_db
def test_db_real_ship_by_imo_and_name(conn):
    r = VE.screen_vessel(conn=conn, imo='9436941', whitelist={})
    assert r['tier'] == 'CONFIRMED' and len({h['group_key'] for h in r['hits']}) == len(r['hits'])
    assert len(r['hits'][0]['sources']) >= 2
    r = VE.screen_vessel(conn=conn, name='HAO FAN 7', whitelist={})
    assert not any(h['name'].upper().startswith('HAO FAN') for h in r['hits'])


def test_one_word_names_never_match():
    r = run(name='ATTICA')                    # listed one-word name: review only
    assert VE.decision(r)[0] == 'review' and 'single_word' in codes(r['hits'][0]['explanation'])
    assert VE.decision(run(name='ATTICAS'))[0] == 'no_match'       # not the same word: nothing
    assert VE.decision(run(name='OCEANSTAR 1'))[0] == 'match'      # joined form of a longer name


def test_mistyped_imo_with_the_name_is_that_ship():
    r = run(name='OCEAN STAR 1', imo='9074728')
    assert VE.decision(r) [:2] == ('match', '9074729')
    assert VE.decision(run(imo='9074728'))[0] == 'review'


def test_same_name_unlisted_imo_goes_to_review():
    assert VE.decision(run(name='OCEAN STAR 2', imo='9876543'))[0] in ('review',)   # 9876543: valid, unlisted
    assert VE.decision(run(name='OCEAN STAR 2', imo='9074729'))[1] == '9074729'     # the IMO's own ship wins


def test_arabic_sound_key():
    assert VE.name_score('تشونغ تشون غانغ', 'CHONG CHON GANG')[0] >= 90
    assert VE.name_score('ناقلة دال ليك', 'DAL LAKE')[0] >= 90
    assert VE.name_score('أتيكا', 'UTAKI')[0] < 60


def test_call_sign_label_stripped():
    assert VU.norm_call_sign('C/S 3E2333') == '3E2333' and VU.norm_call_sign('CSAB1') == 'CSAB1'
    assert '9420356' in VU.imo_neighbours('9420353') and VU.imo_neighbours('9420356') == []


def test_owner_variants():
    assert set(VE.owner_variants('Skadi Ltd.')) == {'SKADI LTD', 'SKADI LIMITED'}


def test_decision_mapping():
    assert VE.decision({'hits': [], 'owner_hits': []})[0] == 'no_match'
    assert VE.decision({'hits': [], 'owner_hits': [{'tier': 'POTENTIAL'}], 'score': 90}) == ('match', None, 90.0)


def test_owner_hit_list_type_is_a_category_never_a_list_name():
    from screening import vessel_store as VS
    from api.vessels_v1 import _view

    class U:
        is_authenticated = True
        role = 'admin'
    assert VS.list_category('UN_Sanctions') == 'SANCTIONS' and VS.list_category('OFAC_SDN_LIST_X') is None
    assert VS.list_category('EU-Something') is None
    assert VS.category_label('UN_Sanctions', user=U()) == 'Sanctions'
    assert VS.category_label('ofac-weird', 'ar', user=U()) == VS.GENERIC_LIST_LABEL_AR
    r = run(name='NO SUCH SHIP', owner='Irano Hind Shipping Company',
            screen_party=lambda n: [{'name': 'IRANO HIND SHIPPING COMPANY', 'score': 94.0, 'source': 'un',
                                     'list_type': 'UN_Sanctions', 'list_type_raw': 'UN_Sanctions'}])
    assert r['owner_hits'][0]['list_type'] == 'SANCTIONS'
    body = json.dumps(_view(1, r, None))
    assert 'UN_Sanctions' not in body and '"un"' not in body and '"category": "SANCTIONS"' in body


def test_export_cells_are_formula_safe():
    from utils.sheet_safe import cell, row
    assert row(['=HYPERLINK("http://x")', '@SUM(1)', '+1', '-2', 'ok', 5, None]) == \
        ["'=HYPERLINK(\"http://x\")", "'@SUM(1)", "'+1", "'-2", 'ok', 5, '']
    from screening.vessel_routes import _export_rows
    res = run(name='=cmd|calc!A1')
    rows = _export_rows([{'row_no': 2, 'ref': '=HYPERLINK("x")', 'q': res['query'], 'tier': res['tier'],
                          'res': res, 'id': 1}])
    assert all(not str(c).startswith(('=', '@', '+')) for r in rows for c in r)


def test_name_screening_ship_scope():
    from screening import complynex_engine as CE
    CE._VESSEL_SCOPE.set(CE._vessel_scope_for('INDIVIDUAL'))
    assert not CE._vessel_allowed({'entity_type': 'VESSEL', 'source': 'ofac'})
    assert "<> 'VESSEL'" in CE._vessel_sql()
    CE._VESSEL_SCOPE.set(CE._vessel_scope_for('ENTITY'))
    assert CE._vessel_allowed({'entity_type': 'VESSEL', 'source': 'ofac'})            # as before ships had a type
    assert not CE._vessel_allowed({'entity_type': 'VESSEL', 'source': 'opensanctions'})
    assert CE._vessel_allowed({'entity_type': 'ENTITY', 'source': 'opensanctions'})
