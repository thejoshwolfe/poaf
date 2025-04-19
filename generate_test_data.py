#!/usr/bin/env python3

import json
import zlib
import struct

def main():
    data = []

    ############################################################################
    group = "ArchiveHeader/ArchiveFooter"
    ############################################################################

    data.append(Test(group, "empty archive",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf"),
        items=[],
    ))
    data.append(Test(group, "invalid ArchiveHeader",
        fromhex("BEF6F29E" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf"),
        error="ArchiveHeader",
    ))
    data.append(Test(group, "invalid footer_signature",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "06" "eee9ce"),
        error="ArchiveFooter",
    ))
    data.append(Test(group, "invalid footer_checksum",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "05" "eee9cf"),
        error="ArchiveFooter",
    ))
    data.append(Test(group, "index_location out of bounds 1",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0300000000000000" "03" "eee9cf"),
        error="ArchiveFooter",
    ))
    data.append(Test(group, "index_location out of bounds 2",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0900000000000000" "09" "eee9cf"),
        error="ArchiveFooter",
    ))
    data.append(Test(group, "invalid index_crc32",
        fromhex("BEF6F09F" "0300" "0300" "01000000" "0600000000000000" "06" "eee9cf"),
        error="ArchiveFooter",
    ))
    data.append(Test(group, "padding before ArchiveHeader",
        fromhex("00" "BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf"),
        error="ArchiveHeader",
    ))
    data.append(Test(group, "padding after ArchiveFooter",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf" "00"),
        error="ArchiveFooter",
    ))


    ############################################################################
    group = "DataItem"
    ############################################################################

    description = "single item"
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        items=[RegularFile("a.txt", b"")],
    ))

    description = "invalid streaming_signature"
    data_item = fromhex("DCA0" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        error="DataItem",
    ))

    description = "invalid streaming_crc32"
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item + b"xxx")
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        error="DataItem",
    ))


    ############################################################################
    group = "Item contents"
    ############################################################################

    description = "text contents"
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0a00") + b"some text\n"
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0a00000000000000") + crc32(b"some text\n") + fromhex("0500") + b"a.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("2400000000000000" "24" "eee9cf"),
        items=[RegularFile("a.txt", b"some text\n")],
    ))

    description = "binary contents"
    data_item = fromhex("DCAC" "0500") + b"a.bin" + fromhex("0a00") + b"\xff\xff\xff\xff \x00\x00\x00\x00\n"
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0a00000000000000") + crc32(b"\xff\xff\xff\xff \x00\x00\x00\x00\n") + fromhex("0500") + b"a.bin"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("2400000000000000" "24" "eee9cf"),
        items=[RegularFile("a.bin", b"\xff\xff\xff\xff \x00\x00\x00\x00\n")],
    ))

    description = "contents exceeds a single chunk"
    contents = b"\x00" * 65536
    data_item = (
        fromhex("DCAC" "0500") + b"a.bin" +
        fromhex("ffff") +
        contents[0:65535] +
        fromhex("0100") +
        contents[65535:]
    )
    data_item += crc32(data_item)
    data_region = actually_compress(data_item)
    index_location_buf = struct.pack("<Q", 4 + len(data_region))
    index_region = fromhex("0000000000000000" "0000010000000000") + crc32(contents) + fromhex("0500") + b"a.bin"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + index_location_buf + bytes([sum(index_location_buf)]) + fromhex("eee9cf"),
        items=[RegularFile("a.bin", contents, length_encoding=True)],
    ))

    description = "contents exactly a single chunk"
    contents = b"\x00" * 65535
    data_item = (
        fromhex("DCAC" "0500") + b"a.bin" +
        fromhex("ffff") +
        contents +
        fromhex("0000")
    )
    data_item += crc32(data_item)
    data_region = actually_compress(data_item)
    index_location_buf = struct.pack("<Q", 4 + len(data_region))
    index_region = fromhex("0000000000000000" "ffff000000000000") + crc32(contents) + fromhex("0500") + b"a.bin"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + index_location_buf + bytes([sum(index_location_buf)]) + fromhex("eee9cf"),
        items=[RegularFile("a.bin", contents, length_encoding=True)],
    ))


    ############################################################################
    group = "IndexItem inconsistent with DataItem"
    ############################################################################

    description = "DataItem/IndexItem file_name conflict"
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"b.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        error="IndexItem",
    ))

    description = "IndexItem jump_location wrong"
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0600000000000000" "0000000000000000" "00000000" "0500") + b"b.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        error="IndexItem",
    ))

    description = "IndexItem file_size wrong"
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0100000000000000" "00000000" "0500") + b"b.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        error="IndexItem",
    ))

    description = "IndexItem contents_crc32 wrong"
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "01000000" "0500") + b"b.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        error="IndexItem",
    ))

    description = "DataItem/IndexItem file_type conflict"
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0540") + b"b.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        error="IndexItem",
    ))

    ############################################################################
    group = "Stream split"
    ############################################################################

    description = "stream split"
    data_region = (
        compress(fromhex("DCAC" "0500") + b"a.txt") +
        compress(fromhex("0000") + crc32(
            fromhex("DCAC" "0500") + b"a.txt" +
            fromhex("0000")
        ))
    )
    index_region = fromhex("1400000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + fromhex("2100000000000000" "21" "eee9cf"),
        items=[RegularFile("a.txt", b"")],
    ))

    description = "stream split ambiguous start correct"
    data_region = (
        compress(fromhex("DCAC" "0500") + b"a.txt") +
        # This is the true start of the compression stream.
        b"\x00\x00\x00\xff\xff" +
        # This is a decoy.
        compress(fromhex("0000") + crc32(
            fromhex("DCAC" "0500") + b"a.txt" +
            fromhex("0000")
        ))
    )
    index_region = fromhex("1400000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + fromhex("2600000000000000" "26" "eee9cf"),
        items=[RegularFile("a.txt", b"")],
    ))

    description = "stream split ambiguous start incorrect"
    data_region = (
        compress(fromhex("DCAC" "0500") + b"a.txt") +
        # This is the true start of the compression stream.
        b"\x00\x00\x00\xff\xff" +
        # The IndexItem says to start here, which will give you the correct contents,
        # however this is not a split in the compression stream.
        # Simply trying to decompress at this offset and catching problems is insufficient
        # for catching the problem that this test case demonstrates.
        # A reader might need to predict exactly what the index will contain by scanning through the data region first.
        compress(fromhex("0000") + crc32(
            fromhex("DCAC" "0500") + b"a.txt" +
            fromhex("0000")
        ))
    )
    index_region = fromhex("1900000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + fromhex("2600000000000000" "26" "eee9cf"),
        error="IndexItem",
    ))

    ############################################################################
    group = "File Type"
    ############################################################################

    description = "all file types"
    items = [
        RegularFile("a.txt", b"some contents\n"),
        PosixExecutable("b.sh", b"#!/usr/bin/env bash\necho hello\n"),
        EmptyDirectory("dir"),
        Symlink("b", "b.sh"),
    ]
    data.append(Test(group, description,
        archive_from_items(items),
        items=items,
    ))

    description = "directories must have 0-length contents"
    data_item = fromhex("DCAC" "0380") + b"dir" + fromhex("0a00") + b"some text\n"
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0a00000000000000") + crc32(b"some text\n") + fromhex("0380") + b"dir"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("2200000000000000" "22" "eee9cf"),
        error="DataItem",
    ))

    description = "symlink target too long"
    contents = b"a" * 4096
    data_item = (
        fromhex("DCAC" "01c0") + b"b" +
        fromhex("0010") +
        contents
    )
    data_item += crc32(data_item)
    data_region = actually_compress(data_item)
    index_location_buf = struct.pack("<Q", 4 + len(data_region))
    index_region = fromhex("0000000000000000" "0010000000000000") + crc32(contents) + fromhex("01c0") + b"b"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + index_location_buf + bytes([sum(index_location_buf)]) + fromhex("eee9cf"),
        error="DataItem",
    ))

    description = "symlink target way too long"
    contents = b"a" * 65535
    data_item = (
        fromhex("DCAC" "01c0") + b"b" +
        fromhex("ffff") +
        contents +
        fromhex("0000")
    )
    data_item += crc32(data_item)
    data_region = actually_compress(data_item)
    index_location_buf = struct.pack("<Q", 4 + len(data_region))
    index_region = fromhex("0000000000000000" "ffff000000000000") + crc32(contents) + fromhex("01c0") + b"b"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + index_location_buf + bytes([sum(index_location_buf)]) + fromhex("eee9cf"),
        error="DataItem",
    ))

    description = "posix executable contents exceeds a single chunk"
    contents = b"\x00" * 65536
    data_item = (
        fromhex("DCAC" "0540") + b"a.bin" +
        fromhex("ffff") +
        contents[0:65535] +
        fromhex("0100") +
        contents[65535:]
    )
    data_item += crc32(data_item)
    data_region = actually_compress(data_item)
    index_location_buf = struct.pack("<Q", 4 + len(data_region))
    index_region = fromhex("0000000000000000" "0000010000000000") + crc32(contents) + fromhex("0540") + b"a.bin"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + index_location_buf + bytes([sum(index_location_buf)]) + fromhex("eee9cf"),
        items=[PosixExecutable("a.bin", contents, length_encoding=True)],
    ))


    ############################################################################
    group = "file_name"
    ############################################################################

    description = "implicit ancestor dir"
    items = [RegularFile("a/b/c.txt", b"")]
    data.append(Test(group, description,
        archive_from_items(items),
        items=items,
    ))

    description = "empty file name"
    items = [RegularFile("", b"")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "file name contains '.'"
    items = [RegularFile("a/./c.txt", b"")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "file name contains '..'"
    items = [RegularFile("a/../c.txt", b"")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "file name contains '//'"
    items = [RegularFile("a//c.txt", b"")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "file name starts with '/'"
    items = [RegularFile("/c.txt", b"")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "file name looks like absolute path on Windows"
    items = [RegularFile("C:/c.txt", b"")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "file name contains '\\'"
    items = [RegularFile("a\\b\\c.txt", b"")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    for c in "".join(chr(x) for x in range(0, 0x1f + 1)) + '"*:<>?|':
        description = "file name contains '{}'".format(repr(c)[1:-1])
        items = [RegularFile("a{}c.txt".format(c), b"")]
        data.append(Test(group, description,
            archive_from_items(items),
            error="DataItem",
        ))

    description = "file name is invalid UTF-8"
    data_item = fromhex("DCAC" "0500") + b"\xff.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"\xff.txt"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        error="DataItem",
    ))


    ############################################################################
    group = "symlink_target"
    ############################################################################

    description = "symlink to self"
    items = [Symlink("b", "b")]
    data.append(Test(group, description,
        archive_from_items(items),
        items=items,
    ))

    description = "empty symlink target"
    items = [Symlink("b", "")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "symlink target contains '.'"
    items = [Symlink("b", "a/./c.txt")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "symlink target contains '..'"
    items = [Symlink("b", "a/../c.txt")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "symlink target contains '//'"
    items = [Symlink("b", "a//c.txt")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "symlink target starts with '/'"
    items = [Symlink("b", "/c.txt")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "symlink target looks like absolute path on Windows"
    items = [Symlink("b", "C:/c.txt")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "symlink target contains '\\'"
    items = [Symlink("b", "a\\b\\c.txt")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    for c in "".join(chr(x) for x in range(0, 0x1f + 1)) + '"*:<>?|':
        description = "symlink target contains '{}'".format(repr(c)[1:-1])
        items = [Symlink("b", "a{}c.txt".format(c))]
        data.append(Test(group, description,
            archive_from_items(items),
            error="DataItem",
        ))

    description = "symlink target is '.'"
    items = [Symlink("b", ".")]
    data.append(Test(group, description,
        archive_from_items(items),
        items=items,
    ))

    description = "symlink target is '..' but does not escape archive"
    items = [Symlink("a/b", "..")]
    data.append(Test(group, description,
        archive_from_items(items),
        items=items,
    ))

    description = "symlink target contains '..' but does not escape archive"
    items = [Symlink("a/b", "../b.sh")]
    data.append(Test(group, description,
        archive_from_items(items),
        items=items,
    ))

    description = "symlink target contains '../../..' but does not escape archive"
    items = [Symlink("a/b/c/b", "../../../b.sh")]
    data.append(Test(group, description,
        archive_from_items(items),
        items=items,
    ))

    description = "symlink target contains '../../..' and does escape archive"
    items = [Symlink("a/c/b", "../../../b.sh")]
    data.append(Test(group, description,
        archive_from_items(items),
        error="DataItem",
    ))

    description = "symlink target is invalid UTF-8"
    data_item = fromhex("DCAC" "05c0") + b"a.bin" + fromhex("0a00") + b"\xff\xff\xff\xff \x00\x00\x00\x00\n"
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0a00000000000000") + crc32(b"\xff\xff\xff\xff \x00\x00\x00\x00\n") + fromhex("05c0") + b"a.bin"
    data.append(Test(group, description,
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("2400000000000000" "24" "eee9cf"),
        error="DataItem",
    ))


    ############################################################################

    with open("test_data.json", "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

def Test(group, description, contents, *, error=None, items=None):
    if type(contents) == bytes:
        contents = to_sliced_hex(contents)
    else:
        assert type(contents) == list and all(type(x) == str for x in contents), repr(contents)
    test = {
        "description": description,
        "group": group,
        "contents": contents,
    }
    if error != None:
        assert error in ("ArchiveHeader", "DataItem", "IndexItem", "ArchiveFooter")
        test["error"] = error
    if items != None:
        test["items"] = items
    return test

def archive_from_items(items):
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"

    def DataItem(item):
        name = item["name"].encode("utf8")
        if item["type"] in (0, 1): # regular file, posix executable
            contents = from_sliced_hex(item["contents"])
        elif item["type"] == 2: # directory
            contents = b""
        elif item["type"] == 3: # symlink
            contents = item["symlink_target"].encode("utf8")
        data_item = (
            fromhex("DCAC") +
            struct.pack("<H", item["type"] << 14 | len(name)) +
            name +
            # Assumes just one chunk.
            struct.pack("<H", len(contents)) +
            contents
        )
        data_item += crc32(data_item)
        return data_item
    data_region = compress(b"".join(DataItem(item) for item in items))

    def IndexItem(item):
        name = item["name"].encode("utf8")
        if item["type"] in (0, 1): # regular file, posix executable
            contents = from_sliced_hex(item["contents"])
        elif item["type"] == 2: # directory
            contents = b""
        elif item["type"] == 3: # symlink
            contents = item["symlink_target"].encode("utf8")
        return (
            fromhex("0000000000000000") +
            struct.pack("<Q", len(contents)) +
            crc32(contents) +
            struct.pack("<H", item["type"] << 14 | len(name)) +
            name
        )
    index_region = b"".join(IndexItem(item) for item in items)

    index_location_buf = struct.pack("<Q", 4 + len(data_region))
    return (
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + index_location_buf + bytes([sum(index_location_buf)]) + fromhex("eee9cf")
    )

def _file(name, type, contents_bytes, length_encoding=False):
    if length_encoding:
        assert contents_bytes == b"\x00" * len(contents_bytes)
        return {
            "name": name,
            "type": type,
            "contents_length": len(contents_bytes),
        }
    else:
        return {
            "name": name,
            "type": type,
            "contents": to_sliced_hex(contents_bytes),
        }
def RegularFile(name, contents_bytes, length_encoding=False):
    return _file(name, 0, contents_bytes, length_encoding)
def PosixExecutable(name, contents_bytes, length_encoding=False):
    return _file(name, 1, contents_bytes, length_encoding)
def EmptyDirectory(name):
    return {
        "name": name,
        "type": 2,
    }
def Symlink(name, symlink_target):
    return {
        "name": name,
        "type": 3,
        "symlink_target": symlink_target,
    }

def compress(b):
    # Uses deterministic quoting, not actually compressing.
    l = len(b)
    assert l <= 0xffff
    return bytes([
        # Quote
        0x00,
        l & 0xff, l >> 8 & 0xff,
        ~l & 0xff, ~l >> 8 & 0xff,
    ]) + b + (
        # Terminal block.
        b"\x03\x00"
    )

def actually_compress(b):
    return zlib.compress(b, wbits=-zlib.MAX_WBITS)

def fromhex(s):
    return bytes.fromhex(s)

def to_sliced_hex(b):
    result = []
    row_size = 32
    for i in range(0, len(b), row_size):
        slice = b[i:i+row_size]
        if slice:
            result.append(slice.hex())
    return result
def from_sliced_hex(a):
    return b"".join(bytes.fromhex(x) for x in a)

def crc32(b):
    return struct.pack("<L", zlib.crc32(b))

if __name__ == "__main__":
    main()
