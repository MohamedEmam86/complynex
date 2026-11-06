"""Search engine ranking on a small fictional corpus: exact, keyword, partial,
typo, Arabic spelling variants (alef / ta marbuta / ya / diacritics / Arabic-Indic
digits), synonyms and cross-script queries."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from governance import resolution_search as S  # noqa: E402

DOCS = {
    1: dict(t='اعتماد الموازنة التقديرية لعام 2026', s='Approval of the 2026 budget.',
            x='وافق المجلس على اعتماد الموازنة التقديرية للشركة للعام المالي 2026 بإجمالي إيرادات متوقعة 410 مليون جنيه'),
    2: dict(t='ترشيح مراقب حسابات الشركة عن السنة المالية 2025', s='Appointment of the external auditor proposed to the GA.',
            x='قرر المجلس ترشيح مكتب مراجعة لتعيينه مراقباً لحسابات الشركة والعرض على الجمعية العامة'),
    3: dict(t='الموافقة على حد تمويل من البنك بمبلغ 150 مليون جنيه', s='Bank credit facility (loan) up to EGP 150 million.',
            x='الحصول على تسهيل ائتماني متوسط الأجل وتفويض العضو المنتدب في التوقيع'),
    4: dict(t='اعتماد السياسة المحدثة لمكافحة غسل الأموال وتمويل الإرهاب', s='AML/CFT policy version 3 approved.',
            x='منهج تقييم المخاطر وإجراءات العناية الواجبة المعززة'),
    5: dict(t='افتتاح فرعين جديدين في الإسكندرية وأسيوط', s='Opening of two new branches.', x='خطة التوسع الجغرافي'),
    6: dict(t='الموافقة على تعامل مع طرف ذي علاقة: استئجار مقر فرع المنصورة', s='Related-party lease; the interested member recused.',
            x='أفصح العضو عن مصلحته وامتنع عن التصويت'),
    7: dict(t='Approval of the information security policy', s='Cyber security policy approved.', x='The board approved the policy.'),
}
SYN = {'APPROVE': ['اعتماد', 'موافقة', 'approve', 'approval'], 'BUDGET': ['ميزانية', 'موازنة', 'budget'],
       'LOAN': ['قرض', 'تمويل', 'loan', 'financing', 'facility', 'تسهيل ائتماني'], 'AUDITOR': ['مراقب حسابات', 'auditor', 'external auditor'],
       'AML': ['غسل الأموال', 'غسيل الأموال', 'money laundering', 'aml'], 'CFT': ['تمويل الإرهاب', 'terrorist financing'],
       'APPOINT': ['تعيين', 'ترشيح', 'appoint', 'appointment'], 'POLICY': ['سياسة', 'policy'], 'BRANCH': ['فرع', 'فروع', 'branch'],
       'RELATED': ['طرف ذو علاقة', 'related party', 'تعارض المصالح', 'conflict of interest']}


def corpus():
    idx = {k: {f: S.analyse(v) for f, v in d.items()} for k, d in DOCS.items()}
    return S.Corpus(idx, [{'group_code': g, 'term': t} for g, ts in SYN.items() for t in ts])


C = corpus()


def top(q, n=1):
    return [rid for rid, _s, _m in S.rank(C, q, min_score=0.25)][:n]


def score(q, rid):
    return next((round(s * 100) for r, s, _m in S.rank(C, q, min_score=0.0) if r == rid), 0)


def test_analyse_normalises_arabic_and_digits():
    a = S.analyse('إعتمادُ المُوازنة التقديريّة لعام ٢٠٢٦')
    b = S.analyse('اعتماد الموازنه التقديريه لعام 2026')
    assert a == b and '2026' in a
    assert S.analyse('الشركات') == S.analyse('شركة')
    assert S.stem('approved') == S.stem('approval') == S.stem('approve')


def test_exact_and_keyword_queries():
    assert top('تعيين مراقب حسابات') == [2]
    assert top('قرض') == [3]
    assert top('سياسة غسل الاموال') == [4]
    assert top('approve budget') == [1]
    assert top('فرع') in ([5], [6])
    assert set(top('فروع', 2)) == {5, 6}


def test_typos_partial_and_variants():
    assert top('مراقب حسبات') == [2]           # a letter left out
    assert top('الميزانيه') == [1]             # synonym + ta marbuta written as ha
    assert top('موازنه ٢٠٢٦') == [1]           # Arabic-Indic digits
    assert top('غسيل الاموال') == [4]          # colloquial spelling
    assert top('budjet') == [1]                # Latin typo
    assert top('auditer') == [2]
    assert 3 in top('تمو', 3)                  # partial word


def test_cross_script_and_synonyms():
    assert top('loan') == [3]
    assert top('external auditor') == [2]
    assert top('money laundering policy') == [4]
    assert top('related party') == [6]
    assert top('تعارض المصالح') == [6]
    # a phrase synonym beats its single words: terrorist financing is not a loan
    assert score('قرض', 3) > score('قرض', 4)


def test_scores_are_ranked_and_bounded():
    r = S.rank(C, 'اعتماد الموازنة التقديرية', min_score=0.0)
    assert r[0][0] == 1 and 0 < r[0][1] <= 1.0
    assert all(r[i][1] >= r[i + 1][1] for i in range(len(r) - 1))
    assert S.rank(C, 'xyzzy qwerty', min_score=0.25) == []
    assert S.rank(C, '', min_score=0.0) == []


def test_highlight_marks_matched_words_and_escapes():
    rid, s, m = S.rank(C, 'تعيين مراقب حسابات')[0]
    h = str(S.highlight(DOCS[2]['t'], m))
    assert '<mark>مراقب</mark>' in h and '<mark>حسابات</mark>' in h
    assert '&lt;script&gt;' in str(S.highlight('<script>x</script> budget', {'budget'}))
    sn = str(S.snippet('word ' * 200 + 'budget end', {'budget'}, width=80))
    assert '<mark>budget</mark>' in sn and sn.startswith('…')


def test_speed_on_thousands_of_resolutions():
    import time
    words = ['اعتماد', 'موازنة', 'قرض', 'سياسة', 'فرع', 'مراقب', 'حسابات', 'تعيين', 'تعديل', 'approve', 'policy', 'budget',
             'لجنة', 'مخاطر', 'تمويل', 'عقد', 'إيجار', 'شركة', 'مكافآت', 'استراتيجية']
    docs = {i: {'t': S.analyse(' '.join(words[(i * k) % len(words)] for k in range(1, 6)) + f' بند {i}'),
                'x': S.analyse(' '.join(words[(i + k) % len(words)] for k in range(12)))} for i in range(1, 3001)}
    c = S.Corpus(docs, [{'group_code': g, 'term': t} for g, ts in SYN.items() for t in ts])
    t0 = time.time()
    for q in ('تعيين مراقب حسابات', 'سياسه', 'approve budjet', 'قرض تمويل'):
        assert S.rank(c, q)
    assert (time.time() - t0) / 4 < 1.5
