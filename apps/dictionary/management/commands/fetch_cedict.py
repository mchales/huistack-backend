import os
import urllib.request
from urllib.error import URLError, HTTPError

from django.core.management.base import BaseCommand, CommandError


# Known sources (first preferred). Will be tried in order if --url not provided.
DEFAULT_URLS = [
    # Current MDBG export naming
    "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz",
    # Legacy MDBG path
    "https://www.mdbg.net/chinese/export/cedict/cedict_ts.u8.gz",
    # CC-CEDICT GitHub plain text (not gzipped)
    "https://raw.githubusercontent.com/cc-cedict/cc-cedict/master/cedict_ts.u8",
]


class Command(BaseCommand):
    help = "Download the latest CC-CEDICT file to a local path (tries multiple mirrors)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            default=None,
            help="Source URL for CC-CEDICT file (override). If omitted, tries known mirrors.",
        )
        parser.add_argument(
            "--output",
            default=os.path.join("apps", "dictionary", "data", "cedict_ts.u8.gz"),
            help="Destination path for downloaded file (.gz or .u8)",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite the output file if it already exists",
        )

    def handle(self, *args, **options):
        url = options["url"]
        output = options["output"]
        overwrite = options["overwrite"]

        dirname = os.path.dirname(output)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)

        if os.path.exists(output) and not overwrite:
            raise CommandError(
                f"Output already exists: {output}. Use --overwrite to replace it."
            )

        candidates = [url] if url else DEFAULT_URLS
        last_error: Exception | None = None

        for candidate in candidates:
            self.stdout.write(f"Downloading CC-CEDICT from {candidate} ...")
            try:
                with urllib.request.urlopen(candidate) as resp, open(output, "wb") as f:
                    total = 0
                    while True:
                        chunk = resp.read(1024 * 64)
                        if not chunk:
                            break
                        f.write(chunk)
                        total += len(chunk)
                if total == 0:
                    raise CommandError("Downloaded file is empty")
                self.stdout.write(self.style.SUCCESS(f"Saved to {output} ({total} bytes)"))
                return
            except (HTTPError, URLError, OSError) as e:
                last_error = e
                self.stdout.write(self.style.WARNING(f"Failed from {candidate}: {e}"))
                continue

        # If we got here, all attempts failed
        if last_error:
            if isinstance(last_error, HTTPError):
                raise CommandError(f"All mirrors failed. Last HTTP error {last_error.code}: {last_error.reason}") from last_error
            raise CommandError(f"All mirrors failed. Last error: {last_error}") from last_error
        raise CommandError("No download candidates available.")
