"""Friday's sense of time: what day it is, how long ago something was said, and when announced events happen.

Stored times are UTC stamps ('%Y-%m-%dT%H:%M:%SZ'); everything given to the writer is local time, in words.
The 10-day simulation (2026-10-29) showed why this is needed: the writer said "tomorrow" on the day of a dinner,
"before the big day" on the wedding morning, and "about a week" for a 53-hour gap.
"""
import calendar
import datetime
import re
import time

FMT = '%Y-%m-%dT%H:%M:%SZ'
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
NUMBERS = {'a': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'a couple': 2, 'a couple of': 2, 'a few': 3}
# A new conversation starts after this much silence; the saved chat history from before it is not "this conversation".
NEW_CONVERSATION_GAP = 3 * 3600


def parse(stamp):
    return calendar.timegm(time.strptime(stamp, FMT))


def stamp(seconds=None):
    return time.strftime(FMT, time.gmtime(time.time() if seconds is None else seconds))


def local_date(seconds):
    t = time.localtime(seconds)
    return datetime.date(t.tm_year, t.tm_mon, t.tm_mday)


def part_of_day(seconds):
    hour = time.localtime(seconds).tm_hour
    return 'night' if hour < 5 else 'morning' if hour < 12 else 'afternoon' if hour < 17 else 'evening' if hour < 21 else 'night'


def short_date(day):
    return f'{WEEKDAYS[day.weekday()].capitalize()} {MONTHS[day.month - 1].capitalize()} {day.day}'


def now_words(now=None):
    """'Tuesday Nov 10, 7:05 pm (evening)'."""
    now = time.time() if now is None else now
    t = time.localtime(now)
    clock = f'{(t.tm_hour % 12) or 12}:{t.tm_min:02d} {"am" if t.tm_hour < 12 else "pm"}'
    return f'{short_date(local_date(now))}, {clock} ({part_of_day(now)})'


def day_words(day, today):
    """A calendar day relative to today: 'today', 'yesterday', 'tomorrow', 'on Wednesday', 'Saturday Nov 7'."""
    days = (day - today).days
    if days == 0: return 'today'
    if days == -1: return 'yesterday'
    if days == 1: return 'tomorrow'
    if -6 <= days < 0: return 'last ' + WEEKDAYS[day.weekday()].capitalize() if days <= -6 else WEEKDAYS[day.weekday()].capitalize()
    if 1 < days <= 6: return 'this ' + WEEKDAYS[day.weekday()].capitalize()
    return short_date(day)


def when_words(seconds, now=None):
    """When something was said, relative to now: 'earlier today (morning)', 'yesterday evening', 'Wednesday night', 'Oct 21'."""
    now = time.time() if now is None else now
    if now - seconds < 3600:
        return 'just now' if now - seconds < 300 else f'{round((now - seconds) / 60)} minutes ago'
    label = day_words(local_date(seconds), local_date(now))
    part = part_of_day(seconds)
    if label == 'today':
        return f'earlier today ({part})' if part != 'night' else 'last night' if time.localtime(seconds).tm_hour < 5 else 'tonight'
    if label == 'yesterday':
        return 'last night' if part == 'night' and time.localtime(seconds).tm_hour >= 21 else f'yesterday {part}'
    if label.split()[-1].lower() in WEEKDAYS:  # 'Wednesday night', 'last Wednesday evening'
        return f'{label} {part}'
    return label


SPELLED = ('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen')


def gap_words(seconds):
    """A length of time in plain words, exact enough to answer 'how long has it been'. Days are spelled out and anchored
    to a familiar span: given "about 33 hours", the 4B writer answered "about three days" (v33 rerun, 2026-10-29)."""
    if seconds < 90: return 'a minute or so'
    if seconds < 3600: return f'{round(seconds / 60)} minutes'
    hours = round(seconds / 3600)
    if hours < 20: return f'about {hours} hour{"s" if hours != 1 else ""}'
    if hours < 30: return f'about a day ({hours} hours)'
    if hours < 42: return f'about a day and a half ({hours} hours)'
    days = round(seconds / 86400)
    if days < 14: return f'about {SPELLED[days]} days ({hours} hours)' if days < 4 else f'about {SPELLED[days]} days'
    return f'about {SPELLED[min(round(days / 7), 13)]} weeks'


# --- Events the person announces ("concert is tomorrow night", "my sisters wedding is next weekend") ---------------
WHEN = (r"(?P<when>today|tonight|tomorrow(?:\s+(?:night|morning|afternoon|evening))?|this\s+weekend|next\s+weekend|next\s+week|"
        r"(?:this\s+|next\s+|on\s+)?(?:" + '|'.join(WEEKDAYS) + r")(?:\s+(?:night|morning|afternoon|evening))?|"
        r"in\s+(?:\d+|a couple(?: of)?|a few|one|two|three|four|five|six|seven)\s+days|"
        r"(?:on\s+)?(?:" + '|'.join(MONTHS) + r")[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?)")
NOUN = r"(?P<what>(?:(?:my|our|the|a|an|his|her|their)\s+)?(?:[a-z][\w'’-]*\s+){0,3}?[a-z][\w'’-]*)"
FILLER = re.compile(r"(?i)^(?:(?:anyway|anyways|but|and|so|also|plus|oh|ok|okay|well|yeah|btw|then|now|just|because|cause|since)\b[,\s]*)+")
NOT_EVENT = re.compile(r"(?i)^(?:it|that|this|there|which|what|who|he|she|they|i|you|we|today|tomorrow|tonight|everything|nothing|something|anything|life|work|the weather|weather)$")
ANNOUNCE = [
    # "<event> is tomorrow night" / "the wedding's on saturday"
    re.compile(r"(?i)(?:^|[.!?,;]\s*|\band\s+)" + NOUN + r"\s+(?:is|'s|’s|was|are|will be|starts|happens)\s+(?:on\s+|this\s+coming\s+)?" + WHEN + r"(?!\w)"),
    # "I have an exam friday", "going to a concert this weekend", "i've got my sister's wedding next weekend"
    re.compile(r"(?i)\b(?:i\s+have|i've\s+got|ive\s+got|i\s+got|i'm\s+going\s+to|im\s+going\s+to|going\s+to|heading\s+to|headed\s+to)\s+" + NOUN + r"\s+" + WHEN + r"(?!\w)"),
]


def _resolve(when, said):
    """The calendar date a 'when' phrase means, from the local date it was said on."""
    w = re.sub(r'\s+', ' ', when.lower()).strip()
    part = next((p for p in ('night', 'morning', 'afternoon', 'evening') if w.endswith(p)), None)
    if w.startswith('tonight'): return said, 'night'
    if w.startswith('today'): return said, part
    if w.startswith('tomorrow'): return said + datetime.timedelta(days=1), part
    if w == 'this weekend':
        return said + datetime.timedelta(days=(5 - said.weekday()) % 7 if said.weekday() != 6 else 0), None
    if w == 'next weekend':  # said on Thursday Oct 29, "next weekend" is Saturday Nov 7
        if said.weekday() < 5:
            return said + datetime.timedelta(days=(5 - said.weekday()) + 7), None
        return said + datetime.timedelta(days=7 if said.weekday() == 5 else 6), None
    if w == 'next week':
        return said + datetime.timedelta(days=7 - said.weekday()), 'week'
    match = re.match(r'in (\d+|a couple(?: of)?|a few|one|two|three|four|five|six|seven) days', w)
    if match:
        count = int(match.group(1)) if match.group(1).isdigit() else NUMBERS[match.group(1)]
        return said + datetime.timedelta(days=count), None
    day = next((i for i, name in enumerate(WEEKDAYS) if name in w.split()), None)
    if day is not None:
        ahead = (day - said.weekday()) % 7
        if w.startswith('next ') and ahead <= 6 - said.weekday():  # "next Friday" said on a Monday is the following week's
            ahead += 7
        return said + datetime.timedelta(days=ahead), part
    match = re.match(r'(?:on )?(' + '|'.join(MONTHS) + r')[a-z]*\.? (\d{1,2})', w)
    if match:
        month = MONTHS.index(match.group(1)) + 1
        try:
            day_ = datetime.date(said.year, month, int(match.group(2)))
        except ValueError:
            return None, None
        if day_ < said - datetime.timedelta(days=60):
            day_ = day_.replace(year=said.year + 1)
        return day_, None
    return None, None


def owner_words(what):
    """Bind the speaker: 'my sisters wedding' -> "their sister's wedding" (the writer reads it as about them)."""
    what = re.sub(r"(?i)\bmy\b", 'their', what.strip())
    what = re.sub(r"(?i)\bour\b", 'their', what)
    return re.sub(r"(?i)\b(brother|sister|mom|mum|dad|son|daughter|cousin|friend|buddy|boss|wife|husband|girlfriend|boyfriend|fiance|fiancee)s\b(?=\s+\w)", r"\1's", what)


def announced_events(text, said_seconds):
    """Events with a date in this message: [{'what','date','part','evidence'}]. Conservative: needs an explicit 'when'."""
    clean = text.replace('’', "'")
    said = local_date(said_seconds)
    found = []
    for pattern in ANNOUNCE:
        for match in pattern.finditer(clean):
            what = FILLER.sub('', match.group('what').strip())
            if not what or NOT_EVENT.match(what) or len(what) < 3:
                continue
            day, part = _resolve(match.group('when'), said)
            if day is None or (day - said).days > 120:
                continue
            found.append({'what': owner_words(what), 'date': day.isoformat(), 'part': part,
                          'evidence': match.group(0).strip(' ,.;!?')[:160]})
    return found


def event_status(event, now=None):
    """Where an event stands now: {'what', 'when': 'tomorrow night' / 'today' / '2 days ago (Saturday)', 'status'}."""
    now = time.time() if now is None else now
    day = datetime.date.fromisoformat(event['date'])
    today = local_date(now)
    days = (day - today).days
    label = day_words(day, today)
    if event.get('part') and event['part'] != 'week' and days in (-1, 0, 1):
        label = {'today': 'tonight' if event['part'] == 'night' else 'this ' + event['part'],
                 'yesterday': 'last night' if event['part'] == 'night' else 'yesterday ' + event['part'],
                 'tomorrow': 'tomorrow ' + event['part']}[label]
    if days < -1:
        label = f'{-days} days ago ({WEEKDAYS[day.weekday()].capitalize()})'
    elif days > 1:
        label = f'in {days} days ({short_date(day)})' if event.get('part') != 'week' else f'next week (from {short_date(day)})'
    status = 'coming up' if days > 0 else 'today' if days == 0 else 'already happened'
    return {'what': event['what'], 'when': label, 'status': status, 'days_from_today': days}


# --- A reply that puts their event on the wrong day ("the wedding tomorrow" three days out) --------------------------
RELATIVE_DAY = re.compile(r"(?i)\b(today|tonight|this (?:morning|afternoon|evening)|tomorrow|yesterday|last night|in (\d+|two|three|four|five|six|seven) days|(\d+|two|three|four|five|six|seven) days ago)\b")


def wrong_event_day(reply, events):
    """(event, the reply's wrong day word) when the reply puts one of their dated events on a day it isn't on."""
    for event in events or ():
        head = event['what'].split()[-1].lower()
        for mention in re.finditer(r'(?i)\b' + re.escape(head) + r'\b', reply):
            window = reply[max(0, mention.start() - 15):mention.end() + 20]  # "tomorrow's wedding", "the wedding is in three days"
            for word in RELATIVE_DAY.finditer(window):
                said = word.group(1).lower()
                if said in ('today', 'tonight') or said.startswith('this '): days = 0
                elif said == 'tomorrow': days = 1
                elif said in ('yesterday', 'last night'): days = -1
                else:
                    count = word.group(2) or word.group(3)
                    days = (int(count) if count.isdigit() else SPELLED.index(count)) * (1 if word.group(2) else -1)
                if days != event['days_from_today']:
                    return event, word.group(1)
    return None


# --- Time ranges in questions ("what was I worried about yesterday morning?") --------------------------------------
RANGE = re.compile(r"(?i)\b(?P<r>yesterday(?:\s+(?:morning|afternoon|evening|night))?|last\s+night|this\s+morning|earlier\s+today|today|"
                   r"(?:earlier\s+)?this\s+week|last\s+week|(?:over\s+)?the\s+(?:last|past)\s+(?:few\s+days|couple(?:\s+of)?\s+days|week(?:\s+and\s+a\s+half)?|\d+\s+days|two\s+weeks)|"
                   r"(?:on\s+|last\s+)?(?:" + '|'.join(WEEKDAYS) + r")(?:\s+(?:morning|afternoon|evening|night))?|"
                   r"the\s+other\s+day|last\s+time|(?:two|2|three|3|a\s+few|a\s+couple(?:\s+of)?)\s+days\s+ago)\b")
PARTS = {'morning': (5, 12), 'afternoon': (12, 17), 'evening': (17, 21), 'night': (19, 29)}


def _day_start(day):
    return time.mktime((day.year, day.month, day.day, 0, 0, 0, 0, 0, -1))


def time_range(text, now=None):
    """(start, end, label) in epoch seconds for a time phrase in a question, or ('last_conversation', label), or None."""
    match = RANGE.search(text.replace('’', "'"))
    if not match:
        return None
    now = time.time() if now is None else now
    phrase = re.sub(r'\s+', ' ', match.group('r').lower())
    today = local_date(now)
    if phrase == 'last time':
        return ('last_conversation', 'last time you talked')
    def day_span(day, part=None):
        start = _day_start(day)
        if part:
            low, high = PARTS[part]
            return start + low * 3600, start + high * 3600
        return start, start + 86400
    if phrase.startswith('yesterday') or phrase == 'last night':
        part = 'night' if phrase == 'last night' else (phrase.split()[1] if ' ' in phrase else None)
        return (*day_span(today - datetime.timedelta(days=1), part), phrase)
    if phrase in ('this morning', 'earlier today', 'today'):
        start, end = day_span(today, 'morning' if phrase == 'this morning' else None)
        return start, min(end, now), phrase
    if 'this week' in phrase:
        monday = today - datetime.timedelta(days=today.weekday())
        return _day_start(monday), now, phrase
    if phrase == 'last week':
        monday = today - datetime.timedelta(days=today.weekday() + 7)
        return _day_start(monday), _day_start(monday + datetime.timedelta(days=7)), phrase
    span = re.match(r'(?:over )?the (?:last|past) (few days|couple(?: of)? days|week(?: and a half)?|(\d+) days|two weeks)', phrase)
    if span:
        days = {'few days': 4, 'week': 7, 'week and a half': 11, 'two weeks': 14}.get(span.group(1), int(span.group(2)) if span.group(2) else 3)
        return now - days * 86400, now, phrase
    ago = re.match(r'(two|2|three|3|a few|a couple(?: of)?) days ago', phrase)
    if ago:
        count = {'two': 2, '2': 2, 'three': 3, '3': 3, 'a few': 3}.get(ago.group(1), 2)
        return (*day_span(today - datetime.timedelta(days=count)), phrase)
    if phrase == 'the other day':
        return _day_start(today - datetime.timedelta(days=5)), _day_start(today - datetime.timedelta(days=1)), phrase
    name = next((w for w in phrase.split() if w in WEEKDAYS), None)
    if name:
        back = (today.weekday() - WEEKDAYS.index(name)) % 7 or 7
        part = next((p for p in PARTS if phrase.endswith(p)), None)
        return (*day_span(today - datetime.timedelta(days=back), part), phrase)
    return None
