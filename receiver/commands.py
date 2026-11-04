"""Deterministic Arabic/English command parser for Receiver's local media library.
No cloud/AI dependency: commands work offline and never execute arbitrary shell code.
"""
import re


def normalize(text):
    text = str(text or '').strip().lower()
    table = str.maketrans({'أ':'ا','إ':'ا','آ':'ا','ى':'ي','ة':'ه','ؤ':'و','ئ':'ي'})
    text = text.translate(table)
    return re.sub(r'\s+', ' ', text)


def _has(q, phrases):
    return any(normalize(x) in q for x in phrases)


def _remove_terms(q, terms):
    # Word boundaries prevent removing "في" from the beginning of "فيديو".
    for term in sorted((normalize(x) for x in terms), key=len, reverse=True):
        q = re.sub(r'(?<!\w)' + re.escape(term) + r'(?!\w)', ' ', q)
    return re.sub(r'\s+', ' ', q).strip()


def parse(text):
    raw = str(text or '').strip()
    q = normalize(raw)
    if not q:
        return {'action': 'help'}
    if _has(q, ('اوقف العرض', 'اخف العرض', 'اخفاء العرض', 'hide display')):
        return {'action': 'hide'}
    if _has(q, ('استعد العرض', 'اظهر العرض', 'restore display')):
        return {'action': 'restore'}
    if _has(q, ('اوقف الصوت', 'اسكت', 'stop audio')):
        return {'action': 'stop_audio'}
    if _has(q, ('اوقف الفيديو', 'اوقف الوسائط', 'stop video', 'stop media')):
        return {'action': 'stop_media'}
    if _has(q, ('حدث المكتبه', 'تحديث المكتبه', 'فهرس الملفات', 'refresh library', 'scan library')):
        return {'action': 'refresh'}
    if _has(q, ('احصائيات', 'عدد الملفات', 'مساحة المكتبه', 'library stats')):
        return {'action': 'stats'}

    # Keep the original filename/alias as entered by the user.
    m = re.match(r'^(?:سم|سمي|سمّ)\s+(?:الملف\s+)?(.+?)\s+(?:باسم|الى)\s+(.+)$', raw)
    if m:
        return {'action': 'alias', 'query': m.group(1).strip(), 'alias': m.group(2).strip()}

    kind = None
    if _has(q, ('صوره', 'صور', 'image', 'photo', 'picture')): kind = 'image'
    elif _has(q, ('فيديو', 'فيديوهات', 'video', 'movie')): kind = 'video'
    elif _has(q, ('صوت', 'موسيقي', 'اغنيه', 'اغاني', 'audio', 'music', 'song')): kind = 'audio'

    newest = _has(q, ('اخر', 'الاحدث', 'جديد', 'last', 'latest', 'newest'))
    if newest:
        return {'action': 'play', 'kind': kind, 'query': '', 'newest': True}

    verbs = ('ابحث عن', 'بحث عن', 'اعرض', 'عرض', 'شغل', 'افتح', 'play', 'show', 'find', 'search')
    if _has(q, verbs):
        terms = _remove_terms(q, verbs + (
            'في', 'عن', 'من', 'التي', 'الذي', 'تحتوي', 'يحتوي', 'فيها', 'عليها', 'على', 'علي', 'جهاز العرض', 'المستقبل',
            'الملف', 'ملف', 'الصوره', 'صوره', 'الصور', 'صور', 'فيديوهات', 'فيديو',
            'الصوت', 'صوت', 'موسيقي', 'اغنيه', 'اغاني', 'image', 'photo', 'picture', 'video',
            'movie', 'audio', 'music', 'song'))
        return {'action': 'play', 'kind': kind, 'query': terms, 'newest': False}
    return {'action': 'search', 'kind': kind, 'query': q, 'newest': False}


def help_text():
    return ('أمثلة: شغل فيديو الترحيب | اعرض صورة السيارة | شغل آخر صوت | '
            'اعرض آخر صورة | سم الملف IMG_123.jpg باسم السيارة | احصائيات المكتبة | اوقف العرض')
