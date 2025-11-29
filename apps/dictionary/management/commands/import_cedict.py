import gzip
import io
import os
import re
from typing import Iterable, List, Optional, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# UPDATE THIS IMPORT PATH TO MATCH YOUR PROJECT STRUCTURE
from apps.dictionary.models import Lemma, Sense, Character, LemmaCharacter


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
    help = "Import CC-CEDICT into Lemma, Character, and Sense models."

    def add_arguments(self, parser):
        parser.add_argument('cedict_path', type=str, help='Path to cc-cedict file (.u8 or .u8.gz)')
        parser.add_argument('--truncate', action='store_true', help='WARNING: Delete all dictionary data before import')
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

        # METRICS
        total_lines = 0
        created_lemmas = 0
        updated_lemmas = 0  # Track backfilled lemmas
        created_senses = 0
        
        # CACHE
        # We store { 'Hanzi': char_id } to avoid excessive DB reads
        self.char_cache = {}

        if truncate:
            self.stdout.write(self.style.WARNING('Truncating Lemma, Sense, and Character tables...'))
            with transaction.atomic():
                LemmaCharacter.objects.all().delete()
                Sense.objects.all().delete()
                Lemma.objects.all().delete()
                Character.objects.all().delete()
        else:
            # Pre-load existing characters if we aren't truncating to prevent duplicates
            self.stdout.write('Loading existing characters into memory...')
            self.char_cache = {c.hanzi: c.id for c in Character.objects.all()}

        # Track processed lemma keys to avoid duplicate sense clearing in one run
        processed_keys = set()
        
        # Batch lists for bulk_create
        lemma_char_batch = []

        self.stdout.write(f"Importing from {path}...")
        
        # We use a large transaction
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
                    if limit and total_lines >= limit:
                        break
                    continue

                lemma_meta = {}
                if store_raw:
                    lemma_meta['source'] = 'cc-cedict'
                    lemma_meta['raw'] = line.strip()

                # 1. Get or Create Lemma
                lemma, created = Lemma.objects.get_or_create(
                    traditional=trad,
                    simplified=simp,
                    pinyin_numbers=pinyin,
                    defaults={
                        'meta': lemma_meta,
                    },
                )

                # 2. Determine if we need to process character links
                should_process_chars = False

                if created:
                    created_lemmas += 1
                    should_process_chars = True
                else:
                    # BACKFILL LOGIC:
                    # If lemma exists, check if it has any characters linked.
                    # If .exists() is False, it means we need to fill the gap.
                    if not lemma.lemma_components.exists():
                        updated_lemmas += 1
                        should_process_chars = True
                        
                    if store_raw:
                        lemma.meta.update(lemma_meta)
                        lemma.save(update_fields=['meta'])

                # 3. Process Components (If New or Backfilling)
                if should_process_chars:
                    self.process_components(lemma, simp, pinyin, lemma_char_batch)

                # 4. Create Senses
                # Ensure unique sense indices per lemma: replace on first encounter in this run
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

                # Periodic Bulk Create & Logging
                if len(lemma_char_batch) >= 5000:
                    self.flush_lemma_chars(lemma_char_batch)

                if total_lines % 5000 == 0:
                    self.stdout.write(f"Processed {total_lines} entries...")

                if limit and total_lines >= limit:
                    break

            # Final flush of remaining batch
            self.flush_lemma_chars(lemma_char_batch)

        self.stdout.write(self.style.SUCCESS(
            f"Done. Lines parsed: {total_lines}. New Lemmas: {created_lemmas}. Backfilled Lemmas: {updated_lemmas}. Senses: {created_senses}."
        ))

    def process_components(self, lemma_obj, simplified_str, pinyin_str, batch_list):
        """
        Matches characters in 'simplified_str' to syllables in 'pinyin_str'.
        Creates Character objects if needed.
        Adds LemmaCharacter objects to the batch_list.
        """
        # CEDICT pinyin is usually space separated: "yin2 hang2"
        pinyin_syllables = pinyin_str.split()

        # Simple alignment check
        alignment_match = len(simplified_str) == len(pinyin_syllables)

        for i, char_str in enumerate(simplified_str):
            # Skip non-Chinese characters (optional, but good for punctuation)
            if not self.is_cjk(char_str):
                continue

            # 1. Get or Create Character ID from cache
            char_id = self.get_or_create_char_id(char_str)

            # 2. Determine Specific Pinyin
            specific_p = "?"
            if alignment_match:
                specific_p = pinyin_syllables[i]

            # 3. Add to batch
            batch_list.append(LemmaCharacter(
                lemma=lemma_obj,
                character_id=char_id,
                order_index=i,
                specific_pinyin=specific_p
            ))

    def get_or_create_char_id(self, char_str):
        """Returns ID from cache, creating DB entry if missing."""
        if char_str in self.char_cache:
            return self.char_cache[char_str]
        
        # Create new character
        # Note: We rely on the DB transaction of the main loop
        char_obj = Character.objects.create(hanzi=char_str)
        self.char_cache[char_str] = char_obj.id
        return char_obj.id

    def flush_lemma_chars(self, batch_list):
        if batch_list:
            LemmaCharacter.objects.bulk_create(batch_list)
            batch_list.clear()

    @staticmethod
    def is_cjk(char):
        # Basic range check for common CJK characters
        # This prevents linking punctuation like '·' or '，'
        cp = ord(char)
        return 0x4E00 <= cp <= 0x9FFF