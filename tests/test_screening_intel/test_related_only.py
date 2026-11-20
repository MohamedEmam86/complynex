"""OpenSanctions records held only as related to a listed party (a sanctioned ship's P&I club, ...) are never
sanctions hits: they are 'RELATED' (information, kind OTHER). Anything with a listing topic, an official-list
dataset or an unclassified dataset stays on the strict side."""
import json

from screening import list_category as LC
from screening import match_classifier as MC
from screening.format_handlers import OpenSanctionsHandler


def test_related_only_rule():
    assert LC.related_only([], ['ua_war_sanctions'], False)
    assert LC.related_only(None, ['ua_war_sanctions', 'ann_graph_topics'], False)
    assert not LC.related_only([], ['ua_war_sanctions'], True)                    # a target is a listing
    assert not LC.related_only(['sanction'], ['ua_war_sanctions'], False)         # its own listing topic
    assert not LC.related_only(['sanction.linked'], ['ua_war_sanctions'], False)  # 50 percent rule: strict side
    assert not LC.related_only(['crime'], ['ua_war_sanctions'], False)
    assert not LC.related_only([], ['gb_fcdo_sanctions'], False)                  # official list
    assert not LC.related_only([], ['ua_war_sanctions', 'us_ofac_sdn'], False)
    assert not LC.related_only([], ['some_unknown_dataset'], False)               # unclassified: strict
    assert not LC.related_only([], ['tokyo_mou_detention'], False)                # background data stays CONTEXT
    assert not LC.related_only([], [], False)


def test_related_category_is_information_not_sanctions():
    assert LC.categorize([LC.RELATED_MARK], ['ua_war_sanctions']) == 'RELATED'
    assert LC.categorize([LC.RELATED_MARK, 'sanction'], ['ua_war_sanctions']) == 'SANCTIONS'
    m = {'source': 'opensanctions', 'list_type': 'RELATED', 'topics': json.dumps([LC.RELATED_MARK]),
         'dataset': 'ua_war_sanctions'}
    assert LC.for_match(m) == 'RELATED' and LC.nature(m)['kind'] == 'OTHER' and MC.classify_match(m) == 'OTHER'
    # the same record without the mark (before the update) was a sanctions hit
    assert LC.for_match(dict(m, list_type='SANCTIONS', topics='[]')) == 'SANCTIONS'


def test_loader_marks_related_parties_only():
    h = OpenSanctionsHandler(rich=False)
    rel = h._parse_line(json.dumps({'id': 'c2', 'schema': 'Company', 'caption': 'Example P&I Club', 'target': False,
                                    'datasets': ['ua_war_sanctions'], 'properties': {'name': ['Example P&I Club']}}))
    lst = h._parse_line(json.dumps({'id': 'c1', 'schema': 'Company', 'caption': 'Listed Co', 'target': True,
                                    'datasets': ['ua_war_sanctions'], 'properties': {'name': ['Listed Co'],
                                                                                     'topics': ['sanction']}}))
    off = h._parse_line(json.dumps({'id': 'c3', 'schema': 'Company', 'caption': 'Named In UK', 'target': False,
                                    'datasets': ['gb_fcdo_sanctions'], 'properties': {'name': ['Named In UK']}}))
    assert rel['list_type'] == 'RELATED' and LC.RELATED_MARK in rel['topics']
    assert lst['list_type'] == 'SANCTIONS' and off['list_type'] == 'SANCTIONS'
    assert h.related_count == 1
