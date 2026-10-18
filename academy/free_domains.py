"""Free-mail and disposable-mail domains rejected (or flagged) at Academy
registration. Lead-quality control, not identity verification."""

FREE_PROVIDERS = frozenset("""
gmail.com googlemail.com yahoo.com yahoo.co.uk yahoo.fr yahoo.de yahoo.es yahoo.it
yahoo.ca yahoo.com.au yahoo.co.in ymail.com rocketmail.com
hotmail.com hotmail.co.uk hotmail.fr hotmail.de hotmail.it hotmail.es outlook.com
outlook.sa outlook.fr outlook.de live.com live.co.uk live.fr msn.com passport.com windowslive.com
icloud.com me.com mac.com aol.com aim.com
protonmail.com proton.me pm.me tutanota.com tutanota.de tuta.io
yandex.com yandex.ru ya.ru mail.ru inbox.ru list.ru bk.ru rambler.ru
gmx.com gmx.net gmx.de gmx.at web.de t-online.de freenet.de
zoho.com zohomail.com mail.com email.com usa.com post.com
qq.com 163.com 126.com sina.com sohu.com aliyun.com
rediffmail.com hushmail.com fastmail.com fastmail.fm lycos.com
naver.com daum.net hanmail.net
laposte.net orange.fr wanadoo.fr free.fr sfr.fr
libero.it virgilio.it tiscali.it alice.it
btinternet.com sky.com virginmedia.com talktalk.net ntlworld.com
comcast.net verizon.net att.net sbcglobal.net cox.net charter.net bellsouth.net earthlink.net
seznam.cz wp.pl o2.pl interia.pl onet.pl
maktoob.com hotmail.com.eg yahoo.com.eg live.com.eg
""".split())

DISPOSABLE = frozenset("""
mailinator.com guerrillamail.com guerrillamail.net sharklasers.com grr.la
10minutemail.com 10minutemail.net temp-mail.org tempmail.com tempmail.net
throwawaymail.com yopmail.com yopmail.fr getnada.com nada.email
dispostable.com maildrop.cc mintemail.com mohmal.com fakeinbox.com
trashmail.com trashmail.de mailnesia.com emailondeck.com spamgourmet.com
tempr.email discard.email moakt.com burnermail.io inboxkitten.com
mailpoof.com tempail.com emailfake.com fakemail.net 33mail.com
""".split())
