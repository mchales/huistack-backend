import gzip
import io
import os
import re
from typing import Iterable, List, Optional, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.dictionary.models import Lemma, Sense


CEDICT_LINE_RE = re.compile(r"^(?P<trad>\S+)\s+(?P<simp>\S+)\s+\[(?P<pinyin>[^\]]+)\]\s+/(?P<defs>.+)/\s*$")


def _iter_lines(path: str) -> Iterable[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    # Support plain text or .gz
    if path.endswith('.gz'):
        with gzip.open(path, mode='rt', encoding='utf-8', errors='ignore') as f:
            for line in f:
                yield line
    else:
        with io.open(path, mode='r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                yield line


def parse_cedict_line(line: str) -> Optional[Tuple[str, str, str, List[str]]]:
    """
    Parse a CC-CEDICT line.
    Returns (traditional, simplified, pinyin_numbers, [glosses]) or None if comment/blank.
    """
    s = line.strip()
    if not s or s.startswith('#'):
        return None
    m = CEDICT_LINE_RE.match(s)
    if not m:
        return None
    trad = m.group('trad')
    simp = m.group('simp')
    pinyin = m.group('pinyin').strip()
    defs = m.group('defs')
    # Split on '/', filter empties
    glosses = [g.strip() for g in defs.split('/') if g.strip()]
    return trad, simp, pinyin, glosses


class Command(BaseCommand):
    help = "Import CC-CEDICT into Lemma and Sense models."

    def add_arguments(self, parser):
        parser.add_argument('cedict_path', type=str, help='Path to cc-cedict file (.u8 or .u8.gz)')
        parser.add_argument('--truncate', action='store_true', help='Delete all Lemma and Sense before import')
        parser.add_argument('--limit', type=int, default=None, help='Limit number of lines for quick testing')
        parser.add_argument('--keep-classifiers', action='store_true', help='Keep CL: classifier gloss segments')
        parser.add_argument('--store-raw', action='store_true', help='Store raw source line in Lemma.meta')

    def handle(self, *args, **options):
        path = options['cedict_path']
        limit = options['limit']
        truncate = options['truncate']
        keep_cls = options['keep_classifiers']
        store_raw = options['store_raw']

        if not os.path.exists(path):
            raise CommandError(f"File not found: {path}")

        total_lines = 0
        created_lemmas = 0
        updated_lemmas = 0
        created_senses = 0

        if truncate:
            self.stdout.write('Truncating Lemma and Sense tables...')
            with transaction.atomic():
                Sense.objects.all().delete()
                Lemma.objects.all().delete()

        # Track processed lemma keys to avoid duplicate sense clearing
        processed_keys = set()

        self.stdout.write(f"Importing from {path}...")
        with transaction.atomic():
            for line in _iter_lines(path):
                parsed = parse_cedict_line(line)
                if not parsed:
                    continue
                trad, simp, pinyin, glosses = parsed
                total_lines += 1

                if not keep_cls:
                    glosses = [g for g in glosses if not g.startswith('CL:')]

                if not glosses:
                    # Nothing to store
                    if limit and total_lines >= limit:
                        break
                    continue

                lemma_meta = {}
                if store_raw:
                    lemma_meta['source'] = 'cc-cedict'
                    lemma_meta['raw'] = line.strip()

                lemma, created = Lemma.objects.get_or_create(
                    traditional=trad,
                    simplified=simp,
                    pinyin_numbers=pinyin,
                    defaults={
                        'meta': lemma_meta,
                    },
                )

                if created:
                    created_lemmas += 1
                else:
                    updated_lemmas += 1
                    # Update meta if requested
                    if store_raw:
                        lemma.meta.update(lemma_meta)
                        lemma.save(update_fields=['meta'])

                # Ensure unique sense indices per lemma: replace on first encounter
                key = (lemma.traditional, lemma.simplified, lemma.pinyin_numbers)
                if key not in processed_keys:
                    Sense.objects.filter(lemma=lemma).delete()
                    processed_keys.add(key)

                for idx, gloss in enumerate(glosses, start=1):
                    Sense.objects.create(
                        lemma=lemma,
                        sense_index=idx,
                        gloss=gloss,
                    )
                    created_senses += 1

                if total_lines % 5000 == 0:
                    self.stdout.write(f"Processed {total_lines} entries...")

                if limit and total_lines >= limit:
                    break

        self.stdout.write(self.style.SUCCESS(
            f"Done. Lines parsed: {total_lines}, Lemmas created: {created_lemmas}, existing: {updated_lemmas}, Senses created: {created_senses}."
        ))

