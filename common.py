
import os, re

archive_magic_number_nostream_index_nocompress = b'\xbe\xf6\xfc\xd0' # 0xD0FCF6BE
archive_magic_number_stream_noindex_nocompress = b'\xbe\xf6\xfc\xe0' # 0xE0FCF6BE
archive_magic_number_stream_index_nocompress   = b'\xbe\xf6\xfc\xf0' # 0xF0FCF6BE
archive_magic_number_nostream_index_deflate    = b'\xbe\xf6\xfc\xd1' # 0xD1FCF6BE
archive_magic_number_stream_noindex_deflate    = b'\xbe\xf6\xfc\xe1' # 0xE1FCF6BE
archive_magic_number_stream_index_deflate      = b'\xbe\xf6\xfc\xf1' # 0xF1FCF6BE

item_signature   = b'\xdc\xac\xa9\xdc'
footer_signature = b'\xb6\xee\xe9\xcf'

STRUCTURE_BOTH = "both"
STRUCTURE_STREAM_ONLY = "stream-only"
STRUCTURE_INDEX_ONLY = "index-only"

COMPRESSION_NONE = "none"
COMPRESSION_DEFLATE = "deflate"

structure_and_compression_to_archive_magic_number = {
    (STRUCTURE_INDEX_ONLY,  COMPRESSION_NONE):    archive_magic_number_nostream_index_nocompress,
    (STRUCTURE_STREAM_ONLY, COMPRESSION_NONE):    archive_magic_number_stream_noindex_nocompress,
    (STRUCTURE_BOTH,        COMPRESSION_NONE):    archive_magic_number_stream_index_nocompress,
    (STRUCTURE_INDEX_ONLY,  COMPRESSION_DEFLATE): archive_magic_number_nostream_index_deflate,
    (STRUCTURE_STREAM_ONLY, COMPRESSION_DEFLATE): archive_magic_number_stream_noindex_deflate,
    (STRUCTURE_BOTH,        COMPRESSION_DEFLATE): archive_magic_number_stream_index_deflate,
}

archive_magic_number_to_structure_and_compression = {v: k for k, v in structure_and_compression_to_archive_magic_number.items()}

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
