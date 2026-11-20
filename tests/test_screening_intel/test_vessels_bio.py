"""Vessel BIO (round 5): the particulars and links the OpenSanctions loader keeps for ships, the role vocabulary,
listed vs merely related parties, and the BIO assembly (identity, history, ownership, sanctions, risk)."""
import json
from datetime import date

from screening import vessel_bio as VB
from screening.format_handlers import OpenSanctionsHandler, expand_rich


def _ship_lines():
    return [
        json.dumps({'id': 'v1', 'schema': 'Vessel', 'caption': 'GRIF', 'datasets': ['x'], 'target': True,
                    'properties': {'name': ['GRIF'], 'imoNumber': ['IMO9332028'], 'buildDate': ['2007-03-05'],
                                   'grossRegisteredTonnage': ['29278'], 'deadweightTonnage': ['47128'],
                                   'previousName': ['Zehra'], 'flag': ['cm'], 'pastFlags': ['pa'],
                                   'topics': ['sanction', 'mare.shadow'], 'createdAt': ['2025-02-26'],
                                   'sourceUrl': ['https://example.test/ship/1'], 'description': ['A tanker.']}}),
        json.dumps({'id': 'c1', 'schema': 'Company', 'caption': 'Grif Maritime Inc', 'target': True, 'datasets': ['x'],
                    'properties': {'name': ['Grif Maritime Inc'], 'country': ['pa'], 'topics': ['sanction']}}),
        json.dumps({'id': 'c2', 'schema': 'Company', 'caption': 'Example P&I Club', 'target': False, 'datasets': ['x'],
                    'properties': {'name': ['Example P&I Club'], 'country': ['us']}}),
        json.dumps({'id': 'o1', 'schema': 'Ownership', 'properties': {'owner': ['c1'], 'asset': ['v1'], 'role': ['owner'],
                                                                     'startDate': ['2025-09-04']}}),
        json.dumps({'id': 'u1', 'schema': 'UnknownLink', 'properties': {'subject': ['c2'], 'object': ['v1'],
                                                                       'role': ['P&I Club'], 'date': ['2026-05-31']}}),
    ]


def test_loader_keeps_bio_particulars_and_link_roles():
    h = OpenSanctionsHandler(rich=False)
    h.party_marks = True
    ents = [e for e in (h._parse_line(x) for x in _ship_lines()) if e]
    assert h.attach_vessel_links(ents) == 1
    assert not any('_os_target' in e or '_os_country' in e for e in ents)       # parse-time marks never stored
    v = expand_rich(next(e for e in ents if e['entity_type'] == 'VESSEL'))['properties']['vessel']
    assert v['deadweight'] == '47128' and v['build_date'] == '2007-03-05' and v['year_built'] == '2007'
    assert v['listed_on'] == '2025-02-26' and 'mare.shadow' in v['topics'] and v['source_urls']
    owners = {o['ref']: o for o in v['owners']}
    assert owners['OS-c1']['role'] == 'owner' and owners['OS-c1']['start'] == '2025-09-04'
    assert owners['OS-c1']['target'] is True and owners['OS-c1']['country'] == 'pa'
    assert owners['OS-c2']['role'] == 'pi_club' and owners['OS-c2']['target'] is False
    assert owners['OS-c2']['party_name'] == 'Example P&I Club' and owners['OS-c2']['as_of'] == '2026-05-31'
    # off (the default, e.g. the rich backfill): the parsed records are exactly as before
    h2 = OpenSanctionsHandler(rich=False)
    assert not any('_os_target' in e for e in (h2._parse_line(x) for x in _ship_lines()) if e)


def test_link_role_vocabulary():
    r = OpenSanctionsHandler.link_role
    assert r('Registered owner') == 'registered_owner' and r('ISM manager and operator') == 'ism_manager'
    assert r('Classification society') == 'class_society' and r('commerce manager') == 'commercial_manager'
    assert r('Related Recognised Organization') == 'recognised_org' and r('Former registered owner') == 'former_owner'
    assert r('Owned or Controlled By', 'Ownership') == 'owner' and r('something else') == 'linked'


def test_type_vocabulary_bilingual():
    assert VB.type_code('Crude Oil Tanker') == 'crude_tanker'
    assert VB.type_code('Navire-citerne pour produits pétroliers') == 'product_tanker'
    assert VB.type_code('Oil tanker/Chemical tanker (OILCHEM)') == 'chemical_oil_tanker'
    assert VB.type_label('Bulk carrier', 'ar') == 'ناقلة بضائع سائبة'
    assert VB.type_label('Something odd') == 'Something odd' and VB.type_label(None) is None


def _rec(**kw):
    r = dict(full_name='GRIF', aliases='[]', source='ofac', source_id='S1', is_active=1, provenance='SANCTION',
             imo='9332028', mmsi='613467601', call_sign='TJM6W', current_flag='Cameroon', flag_history='["Panama", "Gambia"]',
             previous_names='["Zehra"]', vessel_type='Chemical/Products Tanker', gross_tonnage='47128', deadweight='47128',
             build_date='2007-03-05', year_built='2007', measures='["port_ban"]', regimes='["RUSSIA"]', risk_score=45,
             risk_lines='["foc", "renamed"]', topics='["mare.shadow"]', listed_on='2025-02-26', first_seen='2025-02-27',
             datasets=None, source_urls=None, description=None, risk_datasets=None, registration_number=None)
    r.update(kw)
    return r


def test_bio_assembly():
    recs = [_rec(), _rec(source='hmt', source_id='S2', gross_tonnage='29278', deadweight=None, listed_on='2025-05-20'),
            _rec(source='opensanctions', source_id='S3', provenance='RISK', risk_datasets='["black_sea_mou_detention"]',
                 is_active=1, first_seen='2025-06-01', last_seen='2026-11-01')]
    parties = [{'name': 'Grif Maritime Inc', 'role': 'owner', 'party_listed': True, 'country': 'pa', 'start': '2025-09-04'},
               {'name': 'Example Register', 'role': 'class_society', 'party_listed': False},
               {'name': 'A MASTER', 'role': 'master', 'party_listed': False}]
    known = [{'name': 'NEW GRIF', 'kind': 'new_name', 'effective_date': '2026-11-02'}]
    b = VB.build(recs, [], parties, flags={'cameroon': {'foc': True}}, known=known, psc_recs=[recs[2]], lang='en',
                 today=date(2026, 11, 20))
    i = b['identity']
    assert i['gross_tonnage'] == 29278 and i['deadweight'] == 47128          # a 'tonnage' equal to the DWT is not GT
    assert i['age'] == 19 and i['flag_foc'] and i['type_code'] == 'chemical_oil_tanker'
    assert i['class_society'] == 'Example Register' and i['imo_valid']
    assert b['history']['renamed'] and b['history']['timeline'][0]['name'] == 'NEW GRIF'
    assert {f['code'] for f in b['history']['past_flags']} == {'Panama', 'Gambia'}
    assert b['sanctions']['status'] == 'SANCTION' and b['sanctions']['lists'] == 2
    assert b['sanctions']['listing_dates'] == ['2025-02-26', '2025-05-20'] and b['sanctions']['regimes'] == ['RUSSIA']
    assert b['risk']['psc_records'] == 1 and b['risk']['psc_regions'] == ['Black Sea']
    assert any(x['code'] == 'mare.shadow' for x in b['risk']['indicators'])
    roles = [g['role'] for g in b['ownership']]
    assert roles.index('owner') < roles.index('class_society') < roles.index('master')
    assert b['ownership'][0]['parties'][0]['listed']
    ar = VB.build(recs, [], parties, lang='ar', today=date(2026, 11, 20))
    assert ar['identity']['type_label'] == 'ناقلة كيماويات / منتجات نفطية'
    assert ar['ownership'][0]['label'] == 'المالك'
