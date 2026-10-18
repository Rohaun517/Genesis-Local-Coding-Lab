"""Evidence retains hashes and metrics rather than potentially secret process output."""
import hashlib


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def result(argv, code, elapsed, output=b'', timed_out=False):
    return dict(argv=argv, exit_code=code, elapsed_seconds=round(elapsed, 4),
                output_sha256=digest(output), output_bytes=len(output), timed_out=timed_out)
