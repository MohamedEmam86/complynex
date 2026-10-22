"""Fill the regulator's ORIGINAL Word form with a form's answers.

The regulator form must not be amended, so instead of producing our own
layout we write the answers into the content controls of the original .docx
(text, date and checkbox controls, in document order). The definition maps
every item to its control indices ("docx"). Empty text/date controls get
"N/A" (the form forbids blank fields); signature controls stay empty for the
wet or digital signature.
"""
import io
import zipfile
from datetime import date, datetime

from lxml import etree

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
W14 = 'http://schemas.microsoft.com/office/word/2010/wordml'
NS = {'w': W, 'w14': W14}
q = lambda t: '{%s}%s' % (W, t)  # noqa: E731
q14 = lambda t: '{%s}%s' % (W14, t)  # noqa: E731


def _fmt_date(v):
    if not v:
        return ''
    try:
        return datetime.strptime(str(v)[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
    except ValueError:
        return str(v)


def control_values(defn, answers):
    """{control index: ('text', str) | ('check', bool) | ('date', iso)}"""
    vals, signatures = {}, set()

    def put_text(ix, v, kind='text'):
        for i in ix:
            vals[i] = (kind, v)

    for s in defn['sections']:
        for it in s['items']:
            t, a = it['type'], answers.get(it['id'])
            if t == 'signature':
                signatures.update(it.get('docx', []))
                continue
            if t in ('text', 'textarea') and it.get('docx'):
                put_text(it['docx'], (a or '').strip())
            elif t == 'date' and it.get('docx'):
                put_text(it['docx'], (a or '').strip(), 'date')
            elif t in ('choice', 'docstatus'):
                chosen = a if isinstance(a, list) else [a]
                for o in it.get('options', []):
                    for i in o.get('docx', []):
                        vals[i] = ('check', o['v'] in chosen)
            elif t == 'yesno' and isinstance(it.get('docx'), dict):
                for i in it['docx']['yes']:
                    vals[i] = ('check', a == 'yes')
                for i in it['docx']['no']:
                    vals[i] = ('check', a == 'no')
                if it.get('details_docx'):
                    put_text(it['details_docx'], (answers.get(it['id'] + '_details') or '').strip())
            elif t == 'grid' and it.get('docx'):
                kinds = {c['key']: c.get('kind', '') for c in it['columns']}
                rows = a or []
                for r, mapping in enumerate(it['docx']):
                    row = rows[r] if r < len(rows) and isinstance(rows[r], dict) else {}
                    for key, ix in mapping.items():
                        put_text(ix, (row.get(key) or '').strip(), 'date' if kinds.get(key) == 'date' else 'text')
    return vals, signatures


def _set_text(sdt, text, placeholder_style_ids):
    content = sdt.find('w:sdtContent', NS)
    pr = sdt.find('w:sdtPr', NS)
    ph = pr.find('w:showingPlcHdr', NS)
    if ph is not None:
        pr.remove(ph)
    ts = list(content.iter(q('t')))
    if not ts:
        return
    first = ts[0]
    for t in ts[1:]:
        t.text = ''
    run = first.getparent()
    rpr = run.find('w:rPr', NS)
    if rpr is not None:
        rs = rpr.find('w:rStyle', NS)
        if rs is not None and rs.get(q('val')) in placeholder_style_ids:
            rpr.remove(rs)
    for r in content.iter(q('r')):
        rp = r.find('w:rPr', NS)
        if rp is not None:
            rs = rp.find('w:rStyle', NS)
            if rs is not None and rs.get(q('val')) in placeholder_style_ids:
                rp.remove(rs)
    lines = str(text).replace('\r', '').split('\n')
    first.text = lines[0]
    first.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    anchor = first
    for line in lines[1:]:
        br = etree.SubElement(run, q('br'))
        anchor.addnext(br)
        t = etree.Element(q('t'))
        t.text = line
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        br.addnext(t)
        anchor = t


def _set_check(sdt, checked):
    pr = sdt.find('w:sdtPr', NS)
    cb = pr.find('w14:checkbox', NS)
    if cb is None:
        return
    st = cb.find('w14:checked', NS)
    if st is None:
        st = etree.SubElement(cb, q14('checked'))
    st.set(q14('val'), '1' if checked else '0')
    state = cb.find('w14:checkedState' if checked else 'w14:uncheckedState', NS)
    ch = chr(int(state.get(q14('val')), 16)) if state is not None else ('☒' if checked else '☐')
    ts = list(sdt.find('w:sdtContent', NS).iter(q('t')))
    if ts:
        ts[0].text = ch
        for t in ts[1:]:
            t.text = ''


def _set_date(sdt, iso, placeholder_style_ids):
    pr = sdt.find('w:sdtPr', NS)
    d = pr.find('w:date', NS)
    shown = _fmt_date(iso)
    if d is not None and iso and len(str(iso)) >= 10 and str(iso)[4] == '-':
        d.set(q('fullDate'), f'{str(iso)[:10]}T00:00:00Z')
        fmt = d.find('w:dateFormat', NS)
        if fmt is not None:
            fmt.set(q('val'), 'dd/MM/yyyy')
    _set_text(sdt, shown or iso, placeholder_style_ids)


def fill(template_path, defn, answers, na_for_empty=True):
    """Return the filled .docx as bytes."""
    with zipfile.ZipFile(template_path) as zin:
        doc = etree.fromstring(zin.read('word/document.xml'))
        styles = etree.fromstring(zin.read('word/styles.xml'))
        ph_ids = {s.get(q('styleId')) for s in styles.iter(q('style'))
                  if (s.find('w:name', NS) is not None and s.find('w:name', NS).get(q('val')) == 'Placeholder Text')}
        ph_ids.add('PlaceholderText')
        body = doc.find('w:body', NS)
        sdts = list(body.iter(q('sdt')))
        vals, signatures = control_values(defn, answers)
        expected = defn.get('docx_controls')
        if expected and len(sdts) != expected:
            raise ValueError(f'the template has {len(sdts)} fields, the definition expects {expected}')
        for i, s in enumerate(sdts):
            if i == 0 or i in signatures:
                continue
            pr = s.find('w:sdtPr', NS)
            kind = 'check' if pr.find('w14:checkbox', NS) is not None else 'date' if pr.find('w:date', NS) is not None else 'text'
            v = vals.get(i)
            if kind == 'check':
                if v is not None:
                    _set_check(s, bool(v[1]))
                continue
            text = v[1] if v else ''
            if not text:
                if not na_for_empty:
                    continue
                text = 'N/A'
            if kind == 'date':
                _set_date(s, text if text != 'N/A' else '', ph_ids) if text != 'N/A' else _set_text(s, 'N/A', ph_ids)
            else:
                _set_text(s, _fmt_date(text) if v and v[0] == 'date' else text, ph_ids)
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == 'word/document.xml':
                    data = etree.tostring(doc, xml_declaration=True, encoding='UTF-8', standalone=True)
                zout.writestr(item, data)
    return out.getvalue()
