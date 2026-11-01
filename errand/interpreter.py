"""Small offline user-only interpreter; provider strings never enter this module."""
import re


def interpret(text):
    t = text.lower()
    facts = {}
    for service, words in {'plumbing': ['plumb', 'tap', 'leak'], 'electrical': ['electric', 'wiring'], 'ac': ['ac ', 'air condition'], 'cleaning': ['clean']}.items():
        if any(w in t for w in words):
            facts['service'] = service
    for area in ['indiranagar', 'whitefield', 'koramangala', 'hsr', 'jayanagar']:
        if area in t:
            facts['area'] = area.title()
    area = re.search(r'\bin\s+([A-Za-z ]+?)(?=\s+(?:tomorrow|today|next|under|for|before)|[,.;]|$)', text, re.I)
    if area and not facts.get('area'):
        facts['area'] = area.group(1).strip()
    for day in ['tomorrow', 'today', 'next week', 'this week', 'this weekend', 'monday','tuesday','wednesday','thursday','friday','saturday','sunday']:
        if day in t:
            facts['date_range'] = day
    for window in ['morning', 'afternoon', 'evening', 'any']:
        if window in t:
            facts['time_window'] = window
    budget = re.search(r'(?:under|budget|below|₹|rs\.?|inr)\s*₹?\s*([\d,]+)', t)
    if budget:
        facts['budget'] = int(budget.group(1).replace(',',''))
    after = re.search(r'(?:after|earliest|not before)\s*(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?',t)
    if after:
        h=int(after[1]); minute=int(after[2] or 0)
        meridiem=(after[3] or '').replace('.','')
        if meridiem=='pm' and h<12:
            h+=12
        if meridiem=='am' and h==12:
            h=0
        facts['earliest_time']=f'{h:02}:{minute:02}'
        facts.setdefault('time_window','any')
    if 'any time' in t:
        facts.update(time_window='any',earliest_time=None)
    return facts
