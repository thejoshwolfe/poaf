import re

def validate_file_name(file_name_bytes, its_a_symlink_target_and_this_is_the_file_name=None):
    # * the length of `file_name` in bytes must be at least `1` and at most `16383`.
    if len(file_name_bytes) == 0: raise Exception("file name must not be empty")
    if len(file_name_bytes) > 16383: raise Exception("file name too long")
    # * `file_name` must be valid UTF-8.
    file_name_bytes.decode("utf8") # If this raises an error, the file name is invalid.
    # * `file_name` must not contain any bytes in the range `0x00` to `0x1f` (control characters)
    #   or any of the following byte values: `0x22`, `0x2a`, `0x3a`, `0x3c`, `0x3e`, `0x3f`, `0x5c`, `0x7c` (`"*:<>?\|`).
    if re.search(rb'[\x00-\x1f"*:<>?\\|]', file_name_bytes) != None: raise Exception("file name contains invalid characters")

    # Byte value `0x2f` (`/`) is the path delimiter.
    segments = file_name_bytes.split(b"/")
    # * `segment` must not be empty.
    if b"" in segments: raise Exception("file name is not normalized")

    if its_a_symlink_target_and_this_is_the_file_name == None:
        # * `segment` must not be `.` or `..` (byte value `0x2e`).
        if b"." in segments or b".." in segments: raise Exception("file name must not have path traversal segments")
    else:
        # If the entire link target is `.`, it is permitted, otherwise `.` segments are not allowed.
        if b"." in segments and file_name_bytes != b".": raise Exception("file name must be normalized")
        # Let `depth` be the number of `/` bytes in the item's `file_name` (not in the link target).
        depth = len(its_a_symlink_target_and_this_is_the_file_name.split(b"/")) - 1
        # A segment may be `..` only if every prior segment, if any, is also `..`,
        # and the total number of `..` segments does not exceed `depth`.
        up_prefix_match = re.match(rb'^(\.\./)*', file_name_bytes)
        up_prefix_count = len(up_prefix_match.group()) // 3
        if up_prefix_count > depth: raise Exception("symlink target escapes archive")
        file_name_bytes_after_up_prefix = file_name_bytes[up_prefix_match.span()[1]:]
        segments_after_up_prefix = file_name_bytes_after_up_prefix.split(b"/")
        if b".." in segments_after_up_prefix: raise Exception("symlink target must be normalized")

def validate_symlink_target(file_name_bytes, symlink_target_bytes):
    validate_file_name(symlink_target_bytes, file_name_bytes)
