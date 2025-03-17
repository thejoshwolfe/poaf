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
            # ArchiveHeader
            archive_header = self._input.read(4)
            if archive_header[0:3] != archive_signature: raise MalformedInputError("not an archive")
            self.flags = FeatureFlags(archive_header[3])

            if not self.flags.streaming(): raise IncompatibleInputError("archive does not support streaming")
            if self.flags.compression_method() != COMPRESSION_DEFLATE: raise NotImplementedError
            self._start_stream(self._input.tell())

            # ArchiveMetadata
            archive_metadata_size = struct.unpack("<H", self._read(2))[0]
            archive_metadata = self._read(archive_metadata_size)
        except:
            self._input.close()
            raise
        self._remaining_bytes_in_current_contents = 0

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()
    def __iter__(self):
        return self
    def _read(self, n, **kwargs):
        return _read_from_decompressor(self._decompressor, self._input, n, **kwargs)

    def close(self):
        self._input.close()
        self._decompressor = None

    def __next__(self):
        if self._remaining_bytes_in_current_contents != 0: raise ValueError("call read_from_current_entry() until EOF before reading then next item")

        # StreamingItem
        buf = self._read(16, allow_eof=True)
        if len(buf) == 0:
            # Found a split in the stream.
            unused_data = self._decompressor.unused_data
            offset = self._input.tell() - len(unused_data)
            previous_stream_compressed_size = offset - self._stream_start
            self._start_stream(offset)
            self._decompressor = Decompressor()
            # Consume the unused data and then any more data we need.
            buf = self._decompressor.decompress(unused_data, 16)
            buf += self._read(16 - len(buf))
        else:
            previous_stream_compressed_size = 0

        if buf[0:4] != item_signature: raise MalformedInputError("item signature not found")
        (
            name_size,
            header_metadata_size,
            file_size,
        ) = struct.unpack("<HHQ", buf[4:16])

        # Check for sentinel.
        if name_size == header_metadata_size == file_size == 0: raise StopIteration

        item = _read_item(self, previous_stream_compressed_size, name_size, header_metadata_size, file_size)
        self._remaining_bytes_in_current_contents = file_size
        return item

    def read_from_current_entry(self, size=-1):
        # StreamingItem.file_contents
        if size < 0:
            size = self._remaining_bytes_in_current_contents
        else:
            size = min(size, self._remaining_bytes_in_current_contents)
        buf = self._read(size)
        self._remaining_bytes_in_current_contents -= size

        if self._remaining_bytes_in_current_contents == 0:
            # StreamingItem.checksums
            checksums = self._read(self.flags.checksums_size())
            # TODO: do something with it?

        return buf

    def _start_stream(self, stream_start):
        self._decompressor = Decompressor()
        self._stream_start = stream_start

class IndexReader:
    def __init__(self, archive_path):
        self._input = open(archive_path, "rb")
        try:
            # ArchiveHeader
            archive_header = self._input.read(4)
            if archive_header[0:3] != archive_signature: raise MalformedInputError("not an archive")
            self.flags = FeatureFlags(archive_header[3])
            data_region_start = 4

            if not self.flags.index(): raise IncompatibleInputError("archive does not support random access")
            if self.flags.compression_method() != COMPRESSION_DEFLATE: raise NotImplementedError

            # ArchiveFooter
            self._file_size = self._input.seek(0, os.SEEK_END)
            archive_footer_size = self.flags.checksums_size() + 12
            self.archive_footer_start = self._file_size - archive_footer_size
            if not (data_region_start < self.archive_footer_start): raise MalformedInputError("unexpected EOF")
            self._input.seek(self.archive_footer_start)
            archive_footer = self._input.read(archive_footer_size)
            if archive_footer[-4:] != footer_signature: raise MalformedInputError("archive footer signature not found. archive truncated?")
            data_region_compressed_size = struct.unpack("<Q", archive_footer[-12:-4])[0]
            checksums = archive_footer[:-12]

            index_region_start = data_region_start + data_region_compressed_size
            if not (index_region_start < self.archive_footer_start): raise MalformedInputError("data_region_compressed_size out of bounds")

            self._input.seek(index_region_start)
            self._decompressor = Decompressor()

            # ArchiveMetadata
            archive_metadata_size = struct.unpack("<H", self._read(2))[0]
            archive_metadata = self._read(archive_metadata_size)
        except MalformedInputError:
            self._input.close()
            raise

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()
    def __iter__(self):
        return self
    def _read(self, n, **kwargs):
        limit = self.archive_footer_start - self._input.tell()
        return _read_from_decompressor(self._decompressor, self._input, n, buffer_size=min(limit, 0x4000), **kwargs)

    def close(self):
        self._input.close()
        self._decompressor = None

    def __next__(self):
        # IndexItem
        buf = self._read(self.flags.checksums_size() + 20, allow_eof=True)
        if len(buf) == 0:
            # Make sure we've actually reached the end of the Index Region.
            offset = self._input.tell() - len(self._decompressor.unused_data)
            raise StopIteration
        checksums = buf[:-20]
        (
            previous_stream_compressed_size,
            name_size,
            header_metadata_size,
            file_size,
        ) = struct.unpack("<QHHQ", buf[-20:])

        item = _read_item(self, previous_stream_compressed_size, name_size, header_metadata_size, file_size)
        item.checksums = checksums
        return item

class Item:
    def __init__(self, name, file_size, header_metadata, previous_stream_compressed_size):
        self.name = name
        self.file_size = file_size
        self.header_metadata = header_metadata
        self.previous_stream_compressed_size = previous_stream_compressed_size
        self.checksums = None

# MAINTAINER NOTE: I originally tried using a base class for these common methods,
# but then pytlint got confused about undefined symbols. OOP considered harmful.
def _read_item(reader, previous_stream_compressed_size, name_size, header_metadata_size, file_size):
    buf = reader._read(name_size + header_metadata_size)
    name, header_metadata = buf[:name_size], buf[name_size:]

    try:
        name_str = name.decode("utf8")
        if validate_archive_path(name_str) != name:
            raise InvalidArchivePathError
    except (UnicodeDecodeError, InvalidArchivePathError):
        raise MalformedInputError("invalid name found in archive: " + repr(name)) from None

    return Item(name_str, file_size, header_metadata, previous_stream_compressed_size)

def _read_from_decompressor(decompressor, file, n, allow_eof=False, buffer_size=0x4000):
    result = b''
    while len(result) < n:
        if decompressor.eof:
            # Note that you have to check EOF first, as the zlib.Decompress object leaves junk in the other fields once EOF has been hit.
            buf = b''
        elif decompressor.unconsumed_tail:
            buf = decompressor.decompress(decompressor.unconsumed_tail, n)
        else:
            buf = decompressor.decompress(file.read(buffer_size), n)
        if len(buf) == 0:
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
