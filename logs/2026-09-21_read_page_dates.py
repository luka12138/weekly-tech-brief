import json
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser


class Dates(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.buf = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('type') == 'application/ld+json':
            self.active = True
            self.buf = []

    def handle_data(self, data):
        if self.active:
            self.buf.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            self.blocks.append(json.loads(''.join(self.buf)))
            self.active = False


def dates(value):
    found = []
    if isinstance(value, dict):
        fields = {k: v for k, v in value.items() if k in ('@type', 'url', 'headline', 'datePublished', 'dateModified')}
        if 'datePublished' in fields or 'dateModified' in fields:
            found.append(fields)
        for v in value.values():
            found.extend(dates(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(dates(v))
    return found


for url in sys.argv[1:]:
    with urllib.request.urlopen(url, timeout=40) as response:
        parser = Dates()
        parser.feed(response.read().decode())
        print(json.dumps({'url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'status': response.status, 'jsonld_dates': dates(parser.blocks)}, ensure_ascii=False))
