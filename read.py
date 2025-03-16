#!/usr/bin/env python3

import zlib
import struct
import os

from common import *

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("-x", "--extract", metavar="DIR", help=
        "Extract entire archive to the given directory.")
    args = parser.parse_args()

    if args.extract:
        with StreamReader(args.archive, False) as reader:
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

class StreamReader:
    def __init__(self, archive_path, should_validate_index):
        self.should_validate_index = should_validate_index
        if self.should_validate_index: raise NotImplementedError

        self._input = open(archive_path, "rb")
        try:
            archive_signature = self._input.read(4)
            try:
                (structure, compression) = archive_signature_to_structure_and_compression[archive_signature]
            except KeyError:
                raise MalformedInputError("not an archive") from None

            if structure == STRUCTURE_INDEX_ONLY: raise IncompatibleInputError("archive does not support streaming")
            if compression != COMPRESSION_DEFLATE: raise NotImplementedError
            self._decompressor = Decompressor()
            # TODO: ArchiveMetadata
        except MalformedInputError:
            self._input.close()
            raise
        self._remaining_bytes_in_current_contents = -1 # beginning
        self._next_footer_metadata_size = -1

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()
    def __iter__(self):
        return self
    def _read(self, *args, **kwargs): return _read(self, *args, **kwargs)

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
        buf = self._read(17, allow_eof=True)
        if len(buf) == 0:
            # Start a new decompression stream
            unused_data = self._decompressor.unused_data
            data_item_offset = self._input.tell() - len(unused_data)
            self._decompressor = Decompressor()
            # Consume the unused data and then any more data we need.
            buf = self._decompressor.decompress(unused_data, 17)
            buf += self._read(17 - len(buf))

        if buf[0:4] != item_signature: raise MalformedInputError("item magic number mismatch")
        (
            name_size,
            header_metadata_size,
            file_size,
            footer_metadata_size,
        ) = struct.unpack("<HHQB", buf[4:17])

        # Check for sentinel.
        if name_size == header_metadata_size == file_size == 0: raise StopIteration

        self._remaining_bytes_in_current_contents = file_size
        self._next_footer_metadata_size = footer_metadata_size
        return _read_item(self, data_item_offset, name_size, header_metadata_size, file_size, footer_metadata_size)

    def read_from_current_entry(self, size=-1):
        if size < 0:
            size = self._remaining_bytes_in_current_contents
        else:
            size = min(size, self._remaining_bytes_in_current_contents)
        buf = self._read(size)
        self._remaining_bytes_in_current_contents -= size

        if self._remaining_bytes_in_current_contents == 0:
            footer_metadata = self._read(self._next_footer_metadata_size)
            # TODO: do something with it?

        return buf

class IndexReader:
    def __init__(self, archive_path):
        self._input = open(archive_path, "rb")
        try:
            # ArchiveHeader
            archive_signature = self._input.read(4)
            data_region_offset = 4
            try:
                (structure, compression) = archive_signature_to_structure_and_compression[archive_signature]
            except KeyError:
                raise MalformedInputError("not an archive") from None

            if structure == STRUCTURE_STREAM_ONLY: raise IncompatibleInputError("archive does not support random access")
            if compression != COMPRESSION_DEFLATE: raise NotImplementedError

            # ArchiveFooter
            self._file_size = self._input.seek(0, os.SEEK_END)
            index_end = self._file_size - 13 # Adjusted later for footer_metadata_size.
            if not (data_region_offset < index_end): raise MalformedInputError("unexpected EOF")

            self._input.seek(index_end)
            archive_footer = self._input.read(13)
            if archive_footer[9:13] != footer_signature: raise MalformedInputError("archive footer magic number not found. archive truncated?")
            index_offset = struct.unpack("<Q", archive_footer[1:9])[0]
            footer_metadata_size = archive_footer[0]

            if footer_metadata_size > 0:
                index_end -= footer_metadata_size
                if index_end < 4: raise MalformedInputError("archive footer metadata size overflows file size")
                self._input.seek(index_end)
                footer_metadata = self._input.read(footer_metadata_size)
            else:
                footer_metadata = b''

            if not (index_offset < index_end): raise MalformedInputError("index offset out of bounds")

            self._input.seek(index_offset)
            self._decompressor = Decompressor()

            # TODO: ArchiveMetadata
        except MalformedInputError:
            self._input.close()
            raise

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()
    def __iter__(self):
        return self
    def _read(self, *args, **kwargs): return _read(self, *args, **kwargs)

    def close(self):
        self._input.close()
        self._decompressor = None

    def __next__(self):
        buf = self._read(21, allow_eof=True)
        if len(buf) == 0: raise StopIteration
        (
            data_item_offset,
            name_size,
            header_metadata_size,
            file_size,
            footer_metadata_size,
        ) = struct.unpack("<QHHQB", buf)

        item = _read_item(self, data_item_offset, name_size, header_metadata_size, file_size, footer_metadata_size)
        item.footer_metadata = self._read(footer_metadata_size)
        return item

class Item:
    def __init__(self, name, file_size, header_metadata, data_item_offset, footer_metadata_size):
        self.name = name
        self.file_size = file_size
        self.header_metadata = header_metadata
        self.data_item_offset = data_item_offset
        self._footer_metadata_size = footer_metadata_size
        self.footer_metadata = None

# MAINTAINER NOTE: I originally tried using a base class for these common methods,
# but then pytlint got confused about undefined symbols. OOP considered harmful.
def _read_item(reader, data_item_offset, name_size, header_metadata_size, file_size, footer_metadata_size):
    buf = reader._read(name_size + header_metadata_size)
    name, header_metadata = buf[:name_size], buf[name_size:]

    try:
        name_str = name.decode("utf8")
        if validate_archive_path(name_str) != name:
            raise InvalidArchivePathError
    except (UnicodeDecodeError, InvalidArchivePathError):
        raise MalformedInputError("invalid name found in archive: " + repr(name)) from None

    return Item(name_str, file_size, header_metadata, data_item_offset, footer_metadata_size)

def _read(reader, n, allow_eof=False):
    result = b''
    while len(result) < n:
        if reader._decompressor.eof:
            # Note that you have to check EOF first, as the zlib.Decompress object leaves junk in the other fields once EOF has been hit.
            buf = b''
        elif reader._decompressor.unconsumed_tail:
            buf = reader._decompressor.decompress(reader._decompressor.unconsumed_tail, n)
        else:
            buf = reader._decompressor.decompress(reader._input.read(0x4000), n)
        if len(buf) == 0:
            # Assert we've reached the end like we thought.
            if not (reader._input.tell() - len(reader._decompressor.unused_data) == reader._file_size - 12):
                raise MalformedInputError("unexpected end to compressed index")
            break
        result += buf
    if len(result) == n: return result
    if allow_eof and len(result) == 0: return b''
    raise MalformedInputError("unexpected end of stream")


class MalformedInputError(Exception): pass
class IncompatibleInputError(Exception): pass

def Decompressor():
    return zlib.decompressobj(wbits=-zlib.MAX_WBITS)

if __name__ == "__main__":
    main()
