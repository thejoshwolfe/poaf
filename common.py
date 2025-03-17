
import os, re

archive_signature = b'\xbe\xf6\xfc'     # 0xFCF6BE
item_signature    = b'\xdc\xac\xa9\xdc' # 0xDCA9ACDC
footer_signature  = b'\xb6\xee\xe9\xcf' # 0xCFE9EEB6

archive_header_size = 4

# Feature flags
class UnsupportedFeatureError(Exception): pass
class FeatureFlags:
    def __init__(self, flags):
        if bool(flags & 0xC0): raise UnsupportedFeatureError("feature flags")
        compression_method = (flags & 0x03)
        if compression_method not in (0, 1): raise UnsupportedFeatureError("compression method: " + str(compression_method))
        if (flags & 0x0C) == 0: raise UnsupportedFeatureError("no structure")
        self.flags = flags

    @staticmethod
    def from_values(
        compression_method,
        structure,
        crc32,
        sha256,
    ):
        return FeatureFlags(
            {
                COMPRESSION_NONE:    0x00,
                COMPRESSION_DEFLATE: 0x01,
            }[compression_method] |
            {
                STRUCTURE_STREAM_ONLY: 0x04,
                STRUCTURE_INDEX_ONLY:  0x08,
                STRUCTURE_BOTH:        0x0C,
            }[structure] |
            (0x10 if crc32  else 0) |
            (0x20 if sha256 else 0) |
            0
        )

    def compression_method(self):
        value = self.flags & 0x03
        if value == 0: return COMPRESSION_NONE
        if value == 1: return COMPRESSION_DEFLATE
        assert False, "call validate_flags() first"
    def streaming(self): return bool(self.flags & 0x04)
    def index(self):     return bool(self.flags & 0x08)
    def crc32(self):     return bool(self.flags & 0x10)
    def sha256(self):    return bool(self.flags & 0x20)

    def checksums_size(self):
        checksums_size = 0
        if self.crc32():
            checksums_size += 4
        if self.sha256():
            checksums_size += 32
        return checksums_size

STRUCTURE_BOTH = "both"
STRUCTURE_STREAM_ONLY = "stream-only"
STRUCTURE_INDEX_ONLY = "index-only"

COMPRESSION_NONE = "none"
COMPRESSION_DEFLATE = "deflate"


# Paths
class InvalidArchivePathError(Exception): pass
def validate_archive_path(archive_path):
    # Canonicalize slash direction.
    archive_path = archive_path.replace(os.path.sep, "/")
    if len(archive_path) == 0: raise InvalidArchivePathError("Path must not be empty")
    name = archive_path.encode("utf8")
    segments = name.split(b"/")
    # Catch path traversal.
    if len(segments[0]) == 0: raise InvalidArchivePathError("Path must not be absolute", archive_path)
    if b".." in segments: raise InvalidArchivePathError("Path must not contain '..' segments", archive_path)
    # Forbid non-normalized paths.
    if b"" in segments:   raise InvalidArchivePathError("Path must not contain empty segments", archive_path)
    if b"." in segments:  raise InvalidArchivePathError("Path must not contain '.' segments", archive_path)
    # Windows-friendly characters (also no absolute Windows paths, because of ':'.).
    match = re.search(rb'[\x00-\x1f<>:"|?*]', name)
    if match != None: raise InvalidArchivePathError("Path must not contain special characters [\\x00-\\x1f<>:\"|?*]", archive_path)

    # Check length limits.
    if any(len(segment) > 255 for segment in segments): raise InvalidArchivePathError("Path segments must not be longer than 255 bytes", archive_path)
    if len(segments) > 255: raise InvalidArchivePathError("Path must not contain more than 255 segments", archive_path)
    if len(name) > 32767: raise InvalidArchivePathError("Path must not be longer than 32767 bytes", archive_path)

    return name
