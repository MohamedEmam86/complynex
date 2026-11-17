"""Vessel screening V1-V3: identifiers, names, the four layers, and the list handlers' ship data."""
import json

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
    assert VU.name_numbers(VU.norm_name('STAR I')) == ()          # a lone I stays a letter


def _c(wid, name, imo=None, **kw):
    d = dict(watchlist_id=wid, source='ofac', list_type='SANCTIONS', name=name, names=[name] + kw.pop('alt', []),
             previous_names=kw.pop('prev', []), imo=imo, mmsi=kw.pop('mmsi', None), call_sign=None,
             flag=kw.pop('flag', None), flags_past=kw.pop('flags_past', []), type=None, year_built=None,
             measures=['asset_freeze'], owners=[], gross_tonnage=None, legal_status=None)
    d['names'] += d['previous_names']
    return d


CANDS = [_c(1, 'OCEAN STAR 1', '9074729', prev=['SEA PEARL'], mmsi='273111111', flag='Panama',
            flags_past=['Togo', 'Cameroon']),
         _c(2, 'OCEAN STAR 2', '9074731'),
         _c(3, 'AL NOUR', alt=['النور']),
         _c(4, 'OCEAN GLORY', '9387421')]
IDX = {('IMO', '9074729'): [(1, True)], ('IMO', '9074731'): [(2, True)], ('MMSI', '273111111'): [(1, True)],
       ('IMO', '9387421'): [(4, False)]}


def run(**kw):
    return VE.screen_vessel(candidates=CANDS, id_index=IDX, flags={'panama': {'foc': True}}, links={}, **kw)


def test_imo_confirms_even_after_renaming():
    r = run(name='SOMETHING ELSE', imo='IMO 9074729')
    assert r['tier'] == 'CONFIRMED' and r['hits'][0]['watchlist_id'] == 1
    assert any('renamed' in e for e in r['hits'][0]['explanation'])


def test_former_imo_still_confirms():
    r = run(imo='9387421')
    assert r['hits'][0]['watchlist_id'] == 4 and r['tier'] == 'CONFIRMED'
    assert 'former' in r['hits'][0]['explanation'][0]


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
    tops = {h['watchlist_id']: h for h in r['hits']}
    assert 1 in tops and tops[1]['tier'] == 'CONFIRMED'
    assert 4 not in tops                             # same name, different IMO: below threshold


def test_former_name_and_typo():
    r = run(name='SEA PERL')
    assert r['hits'] and r['hits'][0]['watchlist_id'] == 1 and r['tier'] in ('POTENTIAL', 'LOW')


def test_single_common_word_is_not_a_hit():
    assert run(name='OCEAN')['tier'] == 'CLEAR'


def test_arabic_name_finds_the_ship():
    r = run(name='النور')
    assert r['hits'] and r['hits'][0]['watchlist_id'] == 3


def test_mmsi_alone_is_potential_not_confirmed():
    r = run(mmsi='273111111')
    assert r['tier'] == 'POTENTIAL'


def test_risk_lines_never_create_a_match():
    r = run(name='UNKNOWN VESSEL XYZ', imo='9074728', flag='Panama')
    assert r['tier'] == 'CLEAR' and r['risk']['score'] > 0
    assert any('check digit' in l for l in r['risk']['lines']) and any('convenience' in l for l in r['risk']['lines'])


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


def test_opensanctions_vessel_rich_only():
    line = json.dumps({'id': 'v1', 'schema': 'Vessel', 'caption': 'OCEAN STAR', 'datasets': ['x'],
                       'properties': {'name': ['OCEAN STAR'], 'imoNumber': ['9074729'], 'mmsi': ['273111111'],
                                      'flag': ['pa'], 'pastNames': ['SEA PEARL'], 'topics': ['sanction'],
                                      'owner': ['o1']}})
    assert OpenSanctionsHandler(rich=False)._parse_line(line) is None
    e = OpenSanctionsHandler(rich=True)._parse_line(line)
    from screening.format_handlers import expand_rich
    e = expand_rich(e)
    v = e['properties']['vessel']
    assert e['entity_type'] == 'VESSEL' and v['imo'] == '9074729' and 'SEA PEARL' in e['aliases']
    assert v['owners'] == [{'name': None, 'role': 'owner', 'ref': 'OS-o1'}]


def test_people_and_companies_unchanged():
    xml = OFAC_XML.replace(b'<sdnType>Vessel</sdnType>', b'<sdnType>Entity</sdnType>')
    e = OFACHandler().parse(xml)[0]
    assert e['entity_type'] == 'ENTITY' and 'vessel' not in e['properties']
