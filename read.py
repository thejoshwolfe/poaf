#!/usr/bin/env python3

import zlib
import struct
import os

from create import (
    archive_magic_number,
    item_magic_number,
    footer_magic_number,
    validate_archive_path,
)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("-x", "--extract", metavar="DIR", help=
        "Extract entire archive to the given directory.")
    args = parser.parse_args()

    if args.extract:
        with DataReader(args.archive) as reader:
            for item in reader:
                with open(os.path.join(args.extract, item.name), "wb") as f:
                    while True:
                        buf = reader.read_from_current_entry(0x4000)
                        if len(buf) == 0: break
                        f.write(buf)
    else:
        with IndexReader(args.archive) as reader:
            for item in reader:
                print(item.name)

class BaseReader:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()
    def __iter__(self):
        return self

    def _read_item(self, data_item_offset, name_size, metadata_size, file_size):
        buf = self._read(name_size + metadata_size)
        name, metadata = buf[:name_size], buf[name_size:]

        try:
            name_str = name.decode("utf8")
            if validate_archive_path(name_str) != name:
                raise InvalidArchivePathError()
        except (UnicodeDecodeError, InvalidArchivePathError):
            raise MalformedInputError("invalid name found in archive: " + repr(name))

        return Item(name_str, file_size, metadata, data_item_offset)

    def _read(self, n, allow_eof=False):
        result = b''
        while len(result) < n:
            if self._decompressor.eof:
                # Note that you have to check EOF first, as the zlib.Decompress object leaves junk in the other fields once EOF has been hit.
                buf = b''
            elif self._decompressor.unconsumed_tail:
                buf = self._decompressor.decompress(self._decompressor.unconsumed_tail, n)
            else:
                buf = self._decompressor.decompress(self._input.read(0x4000), n)
            if len(buf) == 0:
                # Assert we've reached the end like we thought.
                if not (self._input.tell() - len(self._decompressor.unused_data) == self._file_size - 12):
                    raise MalformedInputError("unexpected end to compressed index")
                break
            result += buf
        if len(result) == n: return result
        if allow_eof and len(result) == 0: return b''
        raise MalformedInputError("unexpected end of stream")

class DataReader(BaseReader):
    def __init__(self, archive_path):
        self._input = open(archive_path, "rb")
        try:
            if self._input.read(4) != archive_magic_number: raise MalformedInputError("not an archive")
            self._decompressor = Decompressor()
        except MalformedInputError:
            self._input.close()
            raise
        self._remaining_bytes_in_current_contents = -1 # beginning

    def close(self):
        self._input.close()
        self._decompressor = None

    def __next__(self):
        # Check state.
        if self._remaining_bytes_in_current_contents == -1:
            # Fist item.
            data_item_offset = 4
        elif self._remaining_bytes_in_current_contents == 0:
            # Might be an unknown offset.
            data_item_offset = 0
        else: raise ValueError("call read_from_current_entry() until EOF before reading then next item")

        # Read fixed-size header stuff.
        buf = self._read(16, allow_eof=True)
        if len(buf) == 0:
            # Start a new decompression stream
            unused_data = self._decompressor.unused_data
            data_item_offset = self._input.tell() - len(unused_data)
            self._decompressor = Decompressor()
            # Consume the unused data and then any more data we need.
            buf = self._decompressor.decompress(unused_data, 16)
            buf += self._read(16 - len(buf))

        if buf[0:4] != item_magic_number: raise MalformedInputError("item magic number mismatch")
        (
            name_size,
            metadata_size,
            file_size,
        ) = struct.unpack("<HHQ", buf[4:16])

        # Check for sentinel.
        if name_size == metadata_size == file_size == 0: raise StopIteration

        self._remaining_bytes_in_current_contents = file_size
        return self._read_item(data_item_offset, name_size, metadata_size, file_size)

    def read_from_current_entry(self, size=-1):
        if size < 0:
            size = self._remaining_bytes_in_current_contents
        else:
            size = min(size, self._remaining_bytes_in_current_contents)
        buf = self._read(size)
        self._remaining_bytes_in_current_contents -= size
        return buf

class IndexReader(BaseReader):
    def __init__(self, archive_path):
        self._input = open(archive_path, "rb")
        try:
            self._file_size = self._input.seek(0, os.SEEK_END)
            if self._file_size < 12: raise MalformedInputError("not an archive")
            index_end = self._input.seek(-12, os.SEEK_END)

            footer = self._input.read(12)
            if footer[8:12] != footer_magic_number: raise MalformedInputError("not an archive") 
            index_offset = struct.unpack("<Q", footer[0:8])[0]
            if not index_offset < index_end: raise MalformedInputError("index offset out of bounds")

            self._input.seek(index_offset)
            self._decompressor = Decompressor()
        except MalformedInputError:
            self._input.close()
            raise

    def close(self):
        self._input.close()
        self._decompressor = None

    def __next__(self):
        buf = self._read(20, allow_eof=True)
        if len(buf) == 0: raise StopIteration
        (
            data_item_offset,
            name_size,
            metadata_size,
            file_size,
        ) = struct.unpack("<QHHQ", buf)

        return self._read_item(data_item_offset, name_size, metadata_size, file_size)

class Item:
    def __init__(self, name, file_size, metadata, data_item_offset):
        self.name = name
        self.file_size = file_size
        self.metadata = metadata
        self.data_item_offset = data_item_offset


class MalformedInputError(Exception): pass

def Decompressor():
    return zlib.decompressobj(wbits=-zlib.MAX_WBITS)

if __name__ == "__main__":
    main()
