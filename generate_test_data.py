#!/usr/bin/env python3

import json
from zlib import crc32 as zlib_crc32
import struct

def main():
    data = []

    # ArchiveHeader and ArchiveFooter
    data.append(Test("empty archive",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf"),
        [],
    ))
    data.append(Test("invalid ArchiveHeader",
        fromhex("BEF6F29E" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf"),
        "error",
    ))
    data.append(Test("invalid footer_signature",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "06" "eee9ce"),
        "error",
    ))
    data.append(Test("invalid footer_checksum",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "05" "eee9cf"),
        "error",
    ))
    data.append(Test("index_location out of bounds 1",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0300000000000000" "03" "eee9cf"),
        "error",
    ))
    data.append(Test("index_location out of bounds 2",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0900000000000000" "09" "eee9cf"),
        "error",
    ))
    data.append(Test("invalid index_crc32",
        fromhex("BEF6F09F" "0300" "0300" "01000000" "0600000000000000" "06" "eee9cf"),
        "error",
    ))
    data.append(Test("padding before ArchiveHeader",
        fromhex("00" "BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf"),
        "error",
    ))
    data.append(Test("padding after ArchiveFooter",
        fromhex("BEF6F09F" "0300" "0300" "00000000" "0600000000000000" "06" "eee9cf" "00"),
        "error",
    ))

    # DataItem
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test("single item",
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        [RegularFile("a.txt", b"")],
    ))

    data_item = fromhex("DCA0" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test("invalid streaming_signature",
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        "error",
    ))

    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item + b"xxx")
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test("invalid streaming_crc32",
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        "error",
    ))

    # IndexItem inconsistent with DataItem
    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0500") + b"b.txt"
    data.append(Test("DataItem/IndexItem file_name conflict",
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        "error",
    ))

    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0600000000000000" "0000000000000000" "00000000" "0500") + b"b.txt"
    data.append(Test("IndexItem jump_location wrong",
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        "error",
    ))

    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0100000000000000" "00000000" "0500") + b"b.txt"
    data.append(Test("IndexItem file_size wrong",
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        "error",
    ))

    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "01000000" "0500") + b"b.txt"
    data.append(Test("IndexItem contents_crc32 wrong",
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        "error",
    ))

    data_item = fromhex("DCAC" "0500") + b"a.txt" + fromhex("0000")
    data_item += crc32(data_item)
    index_region = fromhex("0000000000000000" "0000000000000000" "00000000" "0540") + b"b.txt"
    data.append(Test("DataItem/IndexItem file_type conflict",
        fromhex("BEF6F09F") +
        compress(data_item) +
        compress(index_region) +
        crc32(index_region) + fromhex("1a00000000000000" "1a" "eee9cf"),
        "error",
    ))

    # Stream split
    data_region = (
        compress(fromhex("DCAC" "0500") + b"a.txt") +
        compress(fromhex("0000") + crc32(
            fromhex("DCAC" "0500") + b"a.txt" +
            fromhex("0000")
        ))
    )
    index_region = fromhex("1400000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test("stream split",
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + fromhex("2100000000000000" "21" "eee9cf"),
        [RegularFile("a.txt", b"")],
    ))

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
    data.append(Test("stream split ambiguous start correct",
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + fromhex("2600000000000000" "26" "eee9cf"),
        [RegularFile("a.txt", b"")],
    ))

    data_region = (
        compress(fromhex("DCAC" "0500") + b"a.txt") +
        # This is the true start of the compression stream.
        b"\x00\x00\x00\xff\xff" +
        # The IndexItem says to start here, which will give you the correct contents.
        # Simply trying to decompress and catching problems is insufficient for catching the problem with this test case.
        # A reader might need to predict exactly what the index will contain by scanning through the data region first.
        compress(fromhex("0000") + crc32(
            fromhex("DCAC" "0500") + b"a.txt" +
            fromhex("0000")
        ))
    )
    index_region = fromhex("1900000000000000" "0000000000000000" "00000000" "0500") + b"a.txt"
    data.append(Test("stream split ambiguous start incorrect",
        fromhex("BEF6F09F") +
        data_region +
        compress(index_region) +
        crc32(index_region) + fromhex("2600000000000000" "26" "eee9cf"),
        "error",
    ))


    with open("test_data.json", "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

def Test(description, contents, result):
    if type(contents) == bytes:
        contents = to_sliced_hex(contents)
    else:
        assert type(contents) == list and all(type(x) == str for x in contents)
    return {
        "description": description,
        "contents": contents,
        "result": result
    }

def RegularFile(name, contents_bytes):
    return {
        "name": name,
        "type": 0,
        "contents": to_sliced_hex(contents_bytes),
    }
def PosixExecutable(name, contents_bytes):
    return {
        "name": name,
        "type": 0,
        "contents": to_sliced_hex(contents_bytes),
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

def crc32(b):
    return struct.pack("<L", zlib_crc32(b))

if __name__ == "__main__":
    main()
