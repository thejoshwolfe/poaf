
import os, re

archive_signature = b'\xbe\xf6\xfc' # 0xFCF6BE
item_signature    = b'\xdc\xac'     # 0xACDC
footer_signature  = b'\xee\xe9\xcf' # 0xCFE9EE

FILE_TYPE_NORMAL_FILE = 0
FILE_TYPE_POSIX_EXECUTABLE = 1
FILE_TYPE_DIRECTORY = 2
FILE_TYPE_SYMLINK = 3

# Feature flags
class UnsupportedFeatureError(Exception): pass
class FeatureFlags:
    def __init__(self, flags):
        if (0xF0 & ~flags) >> 4 != flags & 0x0F: raise MalformedInputError("feature flags corrupted")
        if 1 <= (flags & 0x0F) <= 3: raise MalformedInputError("invalid feature flags")
        self.compression = bool(flags & 0x01)
        self.crc32       = bool(flags & 0x02)
        self.streaming   = bool(flags & 0x04)
        self.index       = bool(flags & 0x08)

    @staticmethod
    def from_values(
        compression,
        crc32,
        streaming,
        index,
    ):
        return FeatureFlags(
            (0x01 if compression else 0x10) |
            (0x02 if crc32       else 0x20) |
            (0x04 if streaming   else 0x40) |
            (0x08 if index       else 0x80) |
            0
        )
    def value(self):
        return (
            (0x01 if self.compression else 0x10) |
            (0x02 if self.crc32       else 0x20) |
            (0x04 if self.streaming   else 0x40) |
            (0x08 if self.index       else 0x80) |
            0
        )

# Paths
class InvalidArchivePathError(Exception): pass
def validate_archive_path(archive_path):
    """
    canonicalizes native path separator, then checks validity according to spec, then returns bytes representation.
    """

    # Canonicalize slash direction.
    archive_path = archive_path.replace(os.path.sep, "/")

    # Check length and UTF-8 validity.
    if len(archive_path) == 0: raise InvalidArchivePathError("Path must not be empty")
    name = archive_path.encode("utf8")
    if len(name) > 16383: raise InvalidArchivePathError("Path must not be longer than 16383 bytes", archive_path)
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

    return name

class MalformedInputError(Exception): pass
class IncompatibleInputError(Exception): pass
class ItemContentsTooLongError(Exception): pass
