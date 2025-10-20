from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
except ImportError as exc:  # pragma: no cover - boto3 is optional in some envs
    boto3 = None  # type: ignore
    BotoCoreError = ClientError = NoCredentialsError = Exception  # type: ignore
    _import_error: Exception | None = exc
else:
    _import_error = None


class LessonAudioError(RuntimeError):
    """Raised when an audio URL cannot be resolved or signed."""


@dataclass(frozen=True)
class _S3ObjectIdentity:
    bucket: str
    key: str


def _ensure_boto3_loaded() -> None:
    if boto3 is None or _import_error is not None:  # pragma: no cover - guarded
        raise ImproperlyConfigured(
            "boto3 (and botocore) must be installed to generate lesson audio URLs"
        )


def _aws_bucket() -> str:
    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
    if not bucket:
        raise ImproperlyConfigured("AWS_STORAGE_BUCKET_NAME must be configured for lesson audio")
    return bucket


def _extract_s3_identity(audio_url: str) -> _S3ObjectIdentity:
    """Derive the bucket/key for an audio asset from the stored URL."""
    if not audio_url:
        raise LessonAudioError("Lesson does not have an audio URL configured")

    bucket = _aws_bucket()
    parsed = urlparse(audio_url)

    # Relative or bare key
    if not parsed.scheme:
        key = audio_url.lstrip("/")
        if not key:
            raise LessonAudioError("Lesson audio URL is malformed")
        return _S3ObjectIdentity(bucket=bucket, key=key)

    if parsed.scheme == "s3":
        bucket_name = parsed.netloc or bucket
        key = parsed.path.lstrip("/")
        if not key:
            raise LessonAudioError("Lesson audio URL is missing an object key")
        return _S3ObjectIdentity(bucket=bucket_name, key=key)

    if parsed.scheme in {"http", "https"}:
        netloc = parsed.netloc or ""
        path = parsed.path.lstrip("/")
        if not path:
            raise LessonAudioError("Lesson audio URL is missing a path")

        # Patterns:
        # - bucket.s3.amazonaws.com/key
        # - bucket.s3.<region>.amazonaws.com/key
        # - s3.amazonaws.com/bucket/key
        # - s3.<region>.amazonaws.com/bucket/key
        lower_netloc = netloc.lower()
        region = getattr(settings, "AWS_S3_REGION_NAME", None)
        s3_hosts = {"s3.amazonaws.com"}
        if region:
            s3_hosts.add(f"s3.{region.lower()}.amazonaws.com")
        if ".s3." in lower_netloc:
            bucket_name = lower_netloc.split(".s3.", 1)[0]
            if bucket_name:
                bucket = bucket_name
            return _S3ObjectIdentity(bucket=bucket, key=path)
        if lower_netloc in s3_hosts:
            parts = path.split("/", 1)
            if len(parts) == 2:
                bucket = parts[0] or bucket
                path = parts[1]
            return _S3ObjectIdentity(bucket=bucket, key=path)

        # Custom domain; assume default bucket
        return _S3ObjectIdentity(bucket=bucket, key=path)

    raise LessonAudioError(f"Unsupported audio URL scheme: {parsed.scheme}")


@lru_cache()
def _s3_client():
    _ensure_boto3_loaded()

    client_kwargs = {}
    region = getattr(settings, "AWS_S3_REGION_NAME", None)
    if region:
        client_kwargs["region_name"] = region
    return boto3.client("s3", **client_kwargs)  # type: ignore[call-arg]  # boto3 may be None


def generate_lesson_audio_presigned_url(audio_url: str, expires_in: int = 300) -> str:
    """Return a short-lived download URL for a lesson's audio file."""
    identity = _extract_s3_identity(audio_url)
    client = _s3_client()
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": identity.bucket, "Key": identity.key},
            ExpiresIn=expires_in,
        )
    except (ClientError, BotoCoreError, NoCredentialsError) as exc:  # pragma: no cover
        raise LessonAudioError("Unable to generate audio URL") from exc
