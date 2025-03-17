#!/usr/bin/env python3

import sys, os
import struct
import zlib

from common import *

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("-x", "--extract", metavar="DIR", help=
        "Extract entire archive to the given directory.")
    parser.add_argument("items", nargs="*", help=
        "If specified, only extracts the given items.")
    args = parser.parse_args()

    if args.extract and not args.items:
        # Streaming extract everything
        with StreamReader(args.archive, False) as reader:
            for item in reader:
                with open(os.path.join(args.extract, item.name), "wb") as f:
                    while not item.read_complete():
                        buf = reader.read_from_item(item, 0x4000)
                        f.write(buf)
    else:
        specific_items = set(args.items)
        found_items = set()
        with IndexReader(args.archive) as reader:
            for item in reader:
                if len(specific_items) == 0:
                    # Just list
                    print(item.name)
                elif item.name in specific_items:
                    # Extract this item.
                    found_items.add(item.name)
                    with reader.open_item_reader(item) as input:
                        with open(os.path.join(args.extract, item.name), "wb") as output:
                            buf = input.read(0x4000)
                            if len(buf) == 0: break
                            output.write(buf)
        missing_items = specific_items - found_items
        if len(missing_items) > 0:
            sys.exit("\n".join([
                "ERROR: item not found in archive: " + name
                for name in sorted(missing_items)
            ]))


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
        self._current_item = None

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
        if self._current_item != None: raise ValueError("call read_from_item() until EOF before reading then next item")

        # StreamingItem
        buf = self._read(16)

        if buf[0:4] != item_signature: raise MalformedInputError("item signature not found")
        (
            name_size,
            header_metadata_size,
            file_size,
        ) = struct.unpack("<HHQ", buf[4:16])

        # Check for sentinel.
        if name_size == header_metadata_size == file_size == 0: raise StopIteration

        # Read the rest of the item.
        item = _read_item(self, name_size, header_metadata_size, file_size)

        self._current_item = item
        self._remaining_bytes_in_current_contents = file_size
        return item

    def read_from_item(self, item, size=-1):
        assert self._current_item == item

        # StreamingItem.file_contents
        if size < 0:
            size = self._remaining_bytes_in_current_contents
        else:
            size = min(size, self._remaining_bytes_in_current_contents)

        at_the_start = False
        if item.previous_stream_compressed_size == None:
            # At the very start, there could be an EOF.
            assert self._remaining_bytes_in_current_contents == item.file_size
            at_the_start = True

        buf = self._read(size, allow_eof=at_the_start)

        if at_the_start:
            if len(buf) == 0:
                # Found a stream split.
                unused_data = self._decompressor.unused_data
                offset = self._input.tell() - len(unused_data)
                item.previous_stream_compressed_size = offset - self._stream_start
                self._start_stream(offset)
                self._decompressor = Decompressor()

                # Try again.
                buf = self._read(size)
            else:
                item.previous_stream_compressed_size = 0

        self._remaining_bytes_in_current_contents -= size

        # Check for done.
        if self._remaining_bytes_in_current_contents == 0:
            # StreamingItem.checksums
            item.checksums = self._read(self.flags.checksums_size())
            self._current_item = None

        return buf

    def _start_stream(self, stream_start):
        self._decompressor = Decompressor()
        self._stream_start = stream_start

class IndexReader:
    def __init__(self, archive_path):
        self._archive_path = archive_path
        self._input = open(archive_path, "rb")
        try:
            # ArchiveHeader
            archive_header = self._input.read(4)
            if archive_header[0:3] != archive_signature: raise MalformedInputError("not an archive")
            self.flags = FeatureFlags(archive_header[3])
            data_region_start = 4
            self._stream_start = data_region_start

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
            if self.flags.streaming():
                self._skip_bytes_since_stream_start = 2 + archive_metadata_size
            else:
                self._skip_bytes_since_stream_start = 0
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

        item = _read_item(self, name_size, header_metadata_size, file_size)
        item.previous_stream_compressed_size = previous_stream_compressed_size
        item.checksums = checksums

        # Compute offset for random access.
        if previous_stream_compressed_size > 0:
            # This is a stream split
            item._stream_start = self._stream_start + previous_stream_compressed_size
            item._skip_bytes_until_contents = 0
            self._stream_start = item._stream_start
        else:
            # Getting to this item requires starting at a previous item and skipping bytes.
            item._stream_start = self._stream_start
            item._skip_bytes_until_contents = self._skip_bytes_since_stream_start
            if self.flags.streaming():
                # Account for StreamingItem size before file_contents.
                item._skip_bytes_until_contents += 16 + name_size + header_metadata_size
                self._skip_bytes_since_stream_start = item._skip_bytes_until_contents
        # The next offset will skip this item's contents.
        self._skip_bytes_since_stream_start += file_size
        if self.flags.streaming():
            # Account for StreamingItem size after file_contents.
            self._skip_bytes_since_stream_start += self.flags.checksums_size()

        return item

    def open_item_reader(self, item):
        # This could have also been done without opening another fd and just seeking all over the place.
        f = open(self._archive_path, "rb")
        try:
            f.seek(item._stream_start)
            decompressor = Decompressor()
            skip_bytes = item._skip_bytes_until_contents
            while skip_bytes > 0:
                size = min(skip_bytes, 0x4000)
                skipped_buf = _read_from_decompressor(decompressor, f, size)
                skip_bytes -= len(skipped_buf)
            return ItemReader(decompressor, f, item.file_size)
        except:
            f.close()
            raise

class Item:
    def __init__(self, name, file_size, header_metadata):
        self.name = name
        self.file_size = file_size
        self.header_metadata = header_metadata
        self.previous_stream_compressed_size = None
        self.checksums = None
        self._stream_start = None
        self._skip_bytes_until_contents = None
    def read_complete(self):
        return self.checksums != None

class ItemReader:
    """ I haven't learned how to use the io.* OOP family yet. """
    def __init__(self, decompressor, file, returned_limit):
        self._decompressor = decompressor
        self._file = file
        self._remaining_bytes = returned_limit
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self._file.close()
        self._decompressor = None
    def read(self, size=-1):
        if size < 0:
            limit = self._remaining_bytes
        else:
            limit = min(size, self._remaining_bytes)
        return _read_from_decompressor(self._decompressor, self._file, limit, buffer_size=limit)

# MAINTAINER NOTE: I originally tried using a base class for these common methods,
# but then pytlint got confused about undefined symbols. OOP considered harmful.
def _read_item(reader, name_size, header_metadata_size, file_size):
    buf = reader._read(name_size + header_metadata_size)
    name, header_metadata = buf[:name_size], buf[name_size:]

    try:
        name_str = name.decode("utf8")
        if validate_archive_path(name_str) != name:
            raise InvalidArchivePathError
    except (UnicodeDecodeError, InvalidArchivePathError):
        raise MalformedInputError("invalid name found in archive: " + repr(name)) from None

    return Item(name_str, file_size, header_metadata)

def _read_from_decompressor(decompressor, file, n, allow_eof=False, buffer_size=0x4000):
    if n == 0:
        # While the file.read() and BZ2Decompressor API treats -1 as infinity,
        # the zlib.Decompress API treats 0 as infinity, so we can't allow this value to flow through this function.
        return b''

    result = b''
    while True:
        # Note that you have to check EOF first, as the zlib.Decompress object leaves junk in the other fields once EOF has been hit.
        if decompressor.eof:
            break
        buf = b''
        if decompressor.unconsumed_tail:
            buf += decompressor.decompress(decompressor.unconsumed_tail, n - len(result))
        if not decompressor.unconsumed_tail:
            buf += decompressor.decompress(file.read(buffer_size), n - len(result))
        if len(buf) == 0:
            break
        result += buf
        if len(result) >= n:
            break
    if len(result) == n: return result
    if allow_eof and len(result) == 0: return b''
    raise MalformedInputError("unexpected end of stream")


class MalformedInputError(Exception): pass
class IncompatibleInputError(Exception): pass

def Decompressor():
    return zlib.decompressobj(wbits=-zlib.MAX_WBITS)

if __name__ == "__main__":
    main()
