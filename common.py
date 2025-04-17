
archive_header    = b"\xBE\xF6\xF0\x9F" # 0x9FF0F6BE
item_signature    = b'\xdc\xac'         # 0xACDC
footer_signature  = b'\xee\xe9\xcf'     # 0xCFE9EE

FILE_TYPE_NORMAL_FILE = 0
FILE_TYPE_POSIX_EXECUTABLE = 1
FILE_TYPE_DIRECTORY = 2
FILE_TYPE_SYMLINK = 3

class PoafException(Exception): pass
class InvalidArchivePathError(PoafException): pass
class MalformedInputError(PoafException): pass
class IncompatibleInputError(PoafException): pass
class ItemContentsTooLongError(PoafException): pass

# Paths
def validate_archive_path(archive_path, file_name_of_symlink=None):
    """
    Checks validity according to spec.
    Pass in a str, returns a bytes.
    Give file_name_of_symlink as a str to put this function in symlink validation mode.
    """
    import re

    # Check length and UTF-8 validity.
    if len(archive_path) == 0: raise InvalidArchivePathError("Path must not be empty")
    name = archive_path.encode("utf8")
    length_limit = 4095 if file_name_of_symlink != None else 16383
    if len(name) > length_limit: raise InvalidArchivePathError("Path must not be longer than {} bytes".format(length_limit), archive_path)
    # Windows-friendly characters (also no absolute Windows paths, because of ':'.).
    match = re.search(rb'[\x00-\x1f<>:"|?*]', name)
    if match != None: raise InvalidArchivePathError("Path must not contain special characters [\\x00-\\x1f<>:\"|?*]", archive_path)

    # Catch path traversal and non-normalized paths.
    segments = name.split(b"/")
    if segments[0] == b"": raise InvalidArchivePathError("Path must not be absolute", archive_path)
    if b"" in segments:    raise InvalidArchivePathError("Path must not contain empty segments", archive_path)
    if file_name_of_symlink != None:
        # Limited navigation allowed symlink targets.
        if name != b"." and b"." in segments: raise InvalidArchivePathError("Path must not contain '.' segments", archive_path)
        depth = len(file_name_of_symlink.split("/")) - 1
        while depth > 0 and len(segments) > 0:
            if segments[0] == b"..":
                # Up is ok here.
                del segments[0]
                depth -= 1
            else:
                break
        if b".." in segments: raise InvalidArchivePathError("Symlink target may only have '..' segments at the start up to the depth of the item in the archive", archive_path)
    else:
        # No navigation allowed in file_name fields.
        if b".." in segments: raise InvalidArchivePathError("Path must not contain '..' segments", archive_path)
        if b"." in segments:  raise InvalidArchivePathError("Path must not contain '.' segments", archive_path)

    return name
