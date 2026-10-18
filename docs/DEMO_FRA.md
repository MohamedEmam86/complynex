# ComplyNex — FRA inspection-readiness demo / عرض الجاهزية لتفتيش الهيئة

> **Fictional company only / شركة وهمية فقط.** Every name, figure, lender, branch and
> domain in this demo is invented ("Nile Microfinance S.A.E."). Parameter values are
> marked **"DEMO VALUE"** and are *not* regulatory values. Never run the demo on a
> production installation.
>
> كل الأسماء والأرقام والجهات والفروع في هذا العرض وهمية. قيم المعاملات مُعلَّمة
> **"DEMO VALUE"** وليست قيماً رقابية. لا تُشغِّل العرض على بيئة إنتاج.

---

## 1. Prepare / التجهيز (≈ 2 min)

```bash
python packs/fra_nbfi/scripts/demo_fra.py setup
```

This command:
- loads the lending, prudential, IT and carbon demo data
- enables the FRA NBFI pack and fills the empty parameters with demo values
- runs every control
- opens **15 inspection findings** with action plans
- stores two readiness snapshots: 30 days ago and today

يقوم بالآتي:
- تحميل بيانات العرض (التمويل، الرقابة الاحترازية، تكنولوجيا المعلومات، الكربون)
- تفعيل حزمة الهيئة وملء المعاملات الفارغة بقيم العرض
- تشغيل كل الضوابط
- فتح **15 ملاحظة تفتيش** بخطط تصحيح
- حفظ لقطتين للجاهزية: قبل 30 يوماً واليوم

Log in as an administrator. Create two more users (a reviewer and an approver) to show
segregation of duties.

ادخل كمسؤول نظام، وأنشئ مستخدمَين آخرَين (مراجع ومعتمد) لعرض الفصل بين المهام.

## 2. The story / القصة

| Step / الخطوة | Where / أين | What to show / ماذا تعرض |
|---|---|---|
| 1. Detection — الاكتشاف | Compliance Controls → **Inspection readiness** | Overall score about 22/100 ("Not ready"), score by area, top gaps (critical first), trend line. Open an area to drill down to its controls, evidence and findings. — الدرجة الإجمالية حوالي 22/100، الدرجة حسب المجال، أهم الفجوات، خط الاتجاه، والتعمق في كل مجال. |
| 2. Alert — التنبيه | Compliance Controls → Alerts | Every failed control raised an alert to its owner. Alerts escalate to the Head of Compliance after `rc.escalation_days`. — كل ضابط فاشل أطلق تنبيهاً لمسؤوله، ويُصعَّد لرئيس الالتزام بعد المدة المحددة. |
| 3. Finding — الملاحظة | Compliance Controls → Findings | 15 demo inspection findings, each linked to its control and carrying an action plan. — 15 ملاحظة تفتيش مرتبطة بالضوابط ولكل منها خطة تصحيح. |
| 4. The 15 violations — المخالفات الـ15 | see the table below — انظر الجدول أدناه | Capital, key functions, branches, PAR, fees, refinancing, MLRO, AML report, confirmations, exiting dues, backups, pen test, TLS, carbon data, offsets. |
| 5. Corrective action — الإجراء التصحيحي | run `demo_fra.py remediate` | Six findings are fixed: the data is corrected, the action is marked done, and verification re-runs the control → **pass → closed**. — إصلاح ست ملاحظات: تصحيح البيانات، إتمام الإجراء، ثم إعادة الاختبار → ناجح → إغلاق. |
| 6. Score improvement — تحسن الدرجة | Inspection readiness | The score rises from about 22 to about 30. The trend shows the jump. — ترتفع الدرجة من حوالي 22 إلى 30 ويظهر ذلك في الاتجاه. |
| 7. Repeated violation — المخالفة المتكررة | run `demo_fra.py repeat` | A backup fails again. FRA-051 fails, and its closed finding is **reopened as a repeated violation** with a critical alert. — يفشل النسخ الاحتياطي مجدداً فيُعاد فتح الملاحظة كمخالفة متكررة مع تنبيه حرج. |
| 8. Inspection pack — حزمة التفتيش | Readiness → "Evidence pack (ZIP)" per area | PDF index, `controls.csv`, `run_history.csv` and the evidence files, ready for the inspector. — فهرس PDF وملفات الضوابط وسجل التشغيل والأدلة. |
| 9. Board report — تقرير المجلس | Readiness → Board report → PDF | One page for the board: score, areas, gaps, ageing, trend. — صفحة للمجلس: الدرجة والمجالات والفجوات والأعمار والاتجاه. |
| 10. Calendar — التقويم | Compliance Controls → Regulatory calendar | Submissions, deadlines and extensions, offsets, evidence expiry, findings and actions. Export to `.ics`. Reminders are sent at 14 / 3 / 0 days. — التقارير والمواعيد والمهل والتعويضات وانتهاء الأدلة والملاحظات، مع التصدير والتذكيرات. |

### The 15 demo violations / المخالفات الـ15

| Area / المجال | Control | Violation (fictional data) / المخالفة |
|---|---|---|
| Capital & licensing / رأس المال والترخيص | FRA-001 | Paid-up capital 15m below the 20m demo minimum — رأس المال المدفوع أقل من الحد الأدنى |
| | FRA-006 | Compliance head vacant; CFO not notified; MLRO no-objection pending — وظائف شاغرة أو غير مُخطَر بها |
| | FRA-007 | Branch manager without no-objection; 75-day vacancy — مدير فرع بدون عدم ممانعة وشغور 75 يوماً |
| Origination / المنح | FRA-011 | One branch above the PAR30 threshold — فرع يتجاوز حد محفظة التعثر |
| Pricing / التسعير | FRA-017 | Administrative fee above the cap — رسوم إدارية أعلى من الحد |
| | FRA-023 | Early repayment followed by a costlier loan (also on the AML register) — سداد معجل يعقبه تمويل أعلى تكلفة |
| AML/CFT / مكافحة غسل الأموال | FRA-027 | No independent MLRO registered — لا يوجد مسؤول إبلاغ مستقل مسجل |
| | FRA-053 | Annual AML report not board-approved — التقرير السنوي غير معتمد من المجلس |
| Financial reporting / التقارير المالية | FRA-056 | Lender confirmation 200 days old — مصادقة عمرها 200 يوم |
| | FRA-061 | Exiting shareholder's dues booked as equity — مستحقات مساهم متخارج ضمن حقوق الملكية |
| IT & cyber / تكنولوجيا المعلومات | FRA-051 | On-site, unencrypted and stale backups — نسخ احتياطي داخلي غير مشفر وقديم |
| | FRA-069 | Penetration test expired, no malware test — اختبار اختراق منتهٍ ولا يوجد فحص برمجيات خبيثة |
| | FRA-072 | Portal certificate check failing — فشل فحص شهادة البوابة |
| Climate / المناخ | FRA-CF-02 | Missing month, outlier, unit mismatch, unsupported entry — شهر ناقص وقيمة شاذة وعدم تطابق وحدة |
| | FRA-CF-05 | Offset obligation past its deadline — التزام التعويض تجاوز موعده |

The demo data contains more planted gaps than these 15, so every check has something to
find. The 15 are the ones the story walks through. The remediation step fixes FRA-056,
FRA-061, FRA-051, FRA-069, FRA-007 and FRA-CF-05.

بيانات العرض تحتوي فجوات أكثر من هذه الـ15 حتى يجد كل فحص ما يكتشفه، والـ15 هي محور العرض.

## 3. Extra scenes / مشاهد إضافية

- **Generic, not FRA-only — عام وليس للهيئة فقط:** under Compliance Controls → Frameworks &
  Library, build a small framework (e.g. a data-protection law) in the UI and bind a control
  to a core check. Disabling the FRA pack hides its pages and controls; the core keeps
  working. — ابنِ إطاراً صغيراً من الواجهة واربطه بفحص أساسي؛ تعطيل حزمة الهيئة يخفي صفحاتها وتبقى النواة تعمل.
- **Carbon — الكربون:**
  - Carbon → Carbon accounting → Review & approval: preparer, reviewer and approver must be
    different people, and approval locks the period.
  - Disclosure → PDF / Excel: offsets are shown separately from gross emissions.
  - المُعِد والمراجع والمعتمد أشخاص مختلفون والاعتماد يقفل الفترة، والإفصاح PDF / Excel مع فصل التعويضات.
- **Real TLS check — فحص شهادة حقيقي:** IT resilience → Domains & certificates → add a
  real domain → "Check now". — أضف نطاقاً حقيقياً واضغط افحص الآن.

## 4. Reset / إعادة الضبط

Use a fresh test database, or drop the demo rows. The demo seeds refuse to run where a real
corporate profile or real lending data exists.

استخدم قاعدة بيانات اختبار جديدة؛ سكربتات العرض ترفض العمل إذا وُجد ملف شركة حقيقي أو بيانات تمويل حقيقية.
