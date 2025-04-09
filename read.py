#!/usr/bin/env python3

import sys, os
import struct
import zlib
import tempfile

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
        with StreamReader(args.archive) as reader:
            for item in reader:
                with open(os.path.join(args.extract, item.file_name_str), "wb") as f:
                    while not item.done:
                        f.write(reader.read_from_item(item))
    else:
        specific_items = set(args.items)
        found_items = set()
        with IndexReader(args.archive) as reader:
            for item in reader:
                if len(specific_items) == 0:
                    # Just list
                    print(item.file_name_str)
                elif item.file_name_str in specific_items:
                    # Extract this item.
                    found_items.add(item.file_name_str)
                    with reader.open_item_reader(item) as item_reader:
                        with open(os.path.join(args.extract, item.file_name_str), "wb") as output:
                            while not item_reader.done:
                                output.write(item_reader.read_chunk())
        missing_items = specific_items - found_items
        if len(missing_items) > 0:
            sys.exit("\n".join([
                "ERROR: item not found in archive: " + name
                for name in sorted(missing_items)
            ]))

default_chunk_size = 0x400

class StreamReader:
    def __init__(self, archive_path, validate_index=True):
        self._input = open(archive_path, "rb")
        try:
            # ArchiveHeader
            archive_header = self._input.read(4)
            if archive_header[0:3] != archive_signature: raise MalformedInputError("not an archive")
            self.flags = FeatureFlags(archive_header[3])

            if self.flags.value() == empty_flags:
                # This is going to be easy.
                self._input.close()
                return

            if not self.flags.streaming: raise IncompatibleInputError("archive does not support streaming")
            if self.flags.compression:
                self._decompressor = Decompressor()

            self.validating_index = validate_index and self.flags.index
            if self.validating_index:
                self._index_tmpfile = tempfile.TemporaryFile()
                if self.flags.crc32:
                    self._index_crc32 = 0
        except:
            self._input.close()
            raise
        self._current_item = None

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()
    def __iter__(self):
        return self

    def close(self):
        if self.flags.value() == empty_flags: return
        if self.flags.compression:
            self._decompressor = None
        try:
            if self.validating_index:
                self._index_tmpfile.close()
        finally:
            self._input.close()

    def __next__(self):
        if self.flags.value() == empty_flags: raise StopIteration
        if self._current_item != None: raise ValueError("call read_from_item until done")

        expect_sentinel = self.flags.streaming and self.flags.index and not self.flags.compression

        # StreamingItem
        buf = self._read(4, allow_eof=not expect_sentinel)
        if len(buf) == 0:
            self._done_reading_data_region()
            raise StopIteration

        if buf[0:2] != item_signature: raise MalformedInputError("item signature not found")
        (type_and_name_size,) = struct.unpack("<H", buf[2:])
        file_type, name_size = type_and_name_size >> 14, type_and_name_size & 0x3FFF

        if expect_sentinel and type_and_name_size == 0:
            # Actually a StreamingSentinel.
            self._done_reading_data_region()
            raise StopIteration

        # Read the rest of the StreamingItem.
        name = self._read(name_size)
        file_name_str = _validate_archive_path(name)

        if self.flags.crc32:
            streaming_crc32 = zlib.crc32(buf)
            streaming_crc32 = zlib.crc32(name, streaming_crc32)
        else:
            streaming_crc32 = None

        item = StreamingItem(file_type, file_name_str, streaming_crc32)

        if self.flags.index and not self.flags.compression:
            # Every jump_location is set when compression is not enabled.
            item._predicted_index_item.jump_location = self._input.tell()

        self._current_item = item
        return item

    def read_from_item(self, item, size_limit=0xFFFFFFFFFFFFFFFF):
        if self._current_item != item: raise ValueError("that's not the current item.")

        # Check for stream split before StreamingItem chunked contents.
        allow_eof = self.flags.compression and item._predicted_index_item.file_size == 0
        chunk_size_buf = self._read(2, allow_eof=allow_eof)
        if len(chunk_size_buf) == 0:
            # Found a stream split.
            assert self.flags.compression
            assert self._decompressor.eof
            unused_data = self._decompressor.unused_data
            unused_data_len = len(unused_data)
            if self.flags.index:
                item._predicted_index_item.jump_location = self._input.tell() - unused_data_len
            self._decompressor = Decompressor()

            # Try again
            chunk_size_buf = self._read(2, unused_data_from_previous_stream=unused_data)

        # StreamingItem chunked contents
        (chunk_size,) = struct.unpack("<H", chunk_size_buf)
        buf = self._read(chunk_size)
        item.done = len(buf) < 0xFFFF

        # Track file size
        item._predicted_index_item.file_size += len(buf)
        if item._predicted_index_item.file_size > size_limit: raise ItemContentsTooLongError

        # Compute crc32
        if self.flags.crc32:
            item.streaming_crc32 = zlib.crc32(chunk_size_buf, item.streaming_crc32)
            item.streaming_crc32 = zlib.crc32(buf,            item.streaming_crc32)
            if self.flags.index:
                item._predicted_index_item.contents_crc32 = zlib.crc32(buf, item._predicted_index_item.contents_crc32)

        if item.done:
            self._current_item = None

            # StreamingItem streaming_crc32
            if self.flags.crc32:
                (documented_streaming_crc32,) = struct.unpack("<L", self._read(4))
                if item.streaming_crc32 != documented_streaming_crc32:
                    raise MalformedInputError("streaming_crc32 check failed. calculated: {}, documented: {}".format(item.streaming_crc32, documented_streaming_crc32))

            # IndexItem
            if self.validating_index:
                index_item = item._predicted_index_item
                if self.flags.crc32:
                    contents_crc32_buf = struct.pack("<L", index_item.contents_crc32)
                else:
                    contents_crc32_buf = b""
                name = index_item.file_name_str.encode("utf8")
                type_and_name_size = (index_item.file_type << 14) | len(name)
                self._index_tmpfile.write((
                    contents_crc32_buf +
                    struct.pack("<QQH",
                        index_item.jump_location,
                        index_item.file_size,
                        type_and_name_size,
                    ) +
                    name
                ))
        return buf

    def _done_reading_data_region(self):
        if not self.flags.index:
            # Ensure we hit EOF.
            if self.flags.compression:
                if not (self._decompressor.eof and len(self._decompressor.unconsumed_tail) == 0): raise MalformedInputError("expected EOF after Data Region")
            if len(self._input.read(1)) != 0: raise MalformedInputError("expected EOF after Data Region")
            # That's all there is to check.
            return

        if not self.validating_index:
            # We're choosing not to validate any more of the archive.
            return

        index_size_remaining = self._index_tmpfile.tell()
        self._index_tmpfile.seek(0)

        if self.flags.compression:
            # Start a new decompression stream.
            unused_data = self._decompressor.unused_data
            unused_data_len = len(unused_data)
            self._decompressor = Decompressor()
        else:
            unused_data = None
            unused_data_len = 0
        index_region_location = self._input.tell() - unused_data_len

        index_crc32 = 0
        while index_size_remaining > 0:
            size = min(index_size_remaining, default_chunk_size)
            calculated_buf = self._index_tmpfile.read(size)
            found_buf = self._read(size, unused_data_from_previous_stream=unused_data)
            unused_data = None
            index_size_remaining -= size

            assert len(calculated_buf) == size, "tmpfile modified mid-operation?"
            assert len(found_buf) == size, "allow_eof=False makes this impossible to fail"
            if calculated_buf != found_buf:
                raise MalformedInputError("verifying index failed")
            index_crc32 = zlib.crc32(calculated_buf, index_crc32)

        if self.flags.compression:
            if not (self._decompressor.eof and len(self._decompressor.unconsumed_tail) == 0): raise MalformedInputError("Index Region compression stream too long")
            unused_data = self._decompressor.unused_data
        else:
            unused_data = b""

        # Validate the ArchiveFooter.
        archive_footer_size = (4 if self.flags.crc32 else 0) + 12
        # Ask for 1 too many bytes to make sure we hit EOF.
        documented_archive_footer = unused_data + self._input.read(max(0, archive_footer_size - len(unused_data) + 1))
        if len(documented_archive_footer) > archive_footer_size: raise MalformedInputError("expected EOF after ArchiveFooter")
        if len(documented_archive_footer) < archive_footer_size: raise MalformedInputError("unexpected EOF")

        # Compute what we know the ArchiveFooter should be and compare it all at once.
        if self.flags.crc32:
            index_crc32_buf = struct.pack("<L", index_crc32)
        else:
            index_crc32_buf = b""
        index_region_location_buf = struct.pack("<Q", index_region_location)
        footer_checksum = bytes([0xFF & sum(index_region_location_buf)])
        calculated_archive_footer = (
            index_crc32_buf +
            index_region_location_buf +
            footer_checksum +
            footer_signature
        )

        if documented_archive_footer != calculated_archive_footer: raise MalformedInputError("ArchiveFooter is wrong")

        # Everything's good.

    def _read(self, n, *, allow_eof=False, unused_data_from_previous_stream=None):
        if self.flags.compression:
            return _read_from_decompressor(self._decompressor, self._input, n, allow_eof=allow_eof, unused_data_from_previous_stream=unused_data_from_previous_stream)
        else:
            assert unused_data_from_previous_stream == None
            buf = self._input.read(n)
            if len(buf) == 0 and allow_eof: return buf
            if len(buf) < n: raise MalformedInputError("unexpected EOF")
            return buf

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
            self._skip_bytes_since_stream_start = 0

            if self.flags.value() == empty_flags:
                # This is going to be easy.
                self._input.close()
                return
            if not self.flags.index: raise IncompatibleInputError("archive does not support random access")

            # ArchiveFooter
            self._file_size = self._input.seek(0, os.SEEK_END)
            archive_footer_size = (4 if self.flags.crc32 else 0) + 12
            self.archive_footer_start = self._file_size - archive_footer_size
            if not (4 <= self.archive_footer_start): raise MalformedInputError("unexpected EOF")
            self._input.seek(self.archive_footer_start)
            # archive_footer
            archive_footer = self._input.read(archive_footer_size)

            index_region_location = _validate_archive_footer(archive_footer)

            if self.flags.compression:
                if not (data_region_start <= index_region_location < self.archive_footer_start): raise MalformedInputError("index_region_location out of bounds")
            else:
                if not (data_region_start <= index_region_location <= self.archive_footer_start): raise MalformedInputError("index_region_location out of bounds")

            if self.flags.crc32:
                (self.index_crc32,) = struct.unpack("<L", archive_footer[0:4])
                self._calculated_index_crc32 = 0

            # Start the Index Region.
            self._input.seek(index_region_location)
            if self.flags.compression:
                self._decompressor = Decompressor()

        except:
            self._input.close()
            raise

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()
    def __iter__(self):
        return self
    def _read(self, n, *, allow_eof=False):
        # TODO: an fdslicer would be good here.
        limit = self.archive_footer_start - self._input.tell()
        if self.flags.compression:
            # Pump more from the decompressor.
            return _read_from_decompressor(self._decompressor, self._input, n, compressed_read_limit=limit, allow_eof=allow_eof)
        # Read directly from the Index Region.
        if limit == 0 and allow_eof: return b''
        if limit < n: raise MalformedInputError("unexpected EOF")
        buf = self._input.read(n)
        assert len(buf) == n, "file has been edited while reading"
        return buf

    def close(self):
        if self.flags.value() == empty_flags: return
        self._input.close()
        if self.flags.compression:
            self._decompressor = None

    def __next__(self):
        if self.flags.value() == empty_flags: raise StopIteration
        # IndexItem
        buf = self._read((4 if self.flags.crc32 else 0) + 18, allow_eof=True)
        if len(buf) == 0:
            # Make sure we've actually reached the end of the Index Region.
            if self.flags.compression:
                unused_data_len = len(self._decompressor.unused_data)
                offset = self._input.tell() - unused_data_len
                if offset != self.archive_footer_start: raise MalformedInputError("Index Region compression stream ended too early")
            # Done with the Index Region.
            if self.flags.crc32:
                if self._calculated_index_crc32 != self.index_crc32:
                    raise MalformedInputError("index_crc32 check failed. calculated: {}, documented: {}".format(self._calculated_index_crc32, self.index_crc32))
            raise StopIteration

        if self.flags.crc32:
            (contents_crc32,) = struct.unpack("<L", buf[0:-18])
        else:
            contents_crc32 = None
        (
            jump_location,
            file_size,
            type_and_name_size,
        ) = struct.unpack("<QQH", buf[-18:])
        file_type, name_size = type_and_name_size >> 14, type_and_name_size & 0x3FFF
        name = self._read(name_size)
        file_name_str = _validate_archive_path(name)

        if self.flags.crc32:
            self._calculated_index_crc32 = zlib.crc32(buf, self._calculated_index_crc32)
            self._calculated_index_crc32 = zlib.crc32(name, self._calculated_index_crc32)

        item = IndexItem(jump_location, file_size, file_type, file_name_str, contents_crc32)

        # Compute offset for random access.
        if jump_location == 0 and not self.flags.compression: raise MalformedInputError("every IndexItem.jump_location must be non-zero when Compression is not enabled")
        if jump_location > 0:
            # This is a stream split
            self._stream_start = jump_location
            self._skip_bytes_since_stream_start = 0
        elif self.flags.streaming:
            # Skip the corresponding StreamingItem's fields before the contents.
            self._skip_bytes_since_stream_start += 4 + name_size
        item._stream_start = self._stream_start
        item._skip_bytes_until_contents = self._skip_bytes_since_stream_start

        # For the next item, skip the file_contents of this item.
        self._skip_bytes_since_stream_start += file_size
        if self.flags.streaming:
            chunking_overhead = 2 * ((file_size // 0xFFFF) + 1)
            self._skip_bytes_since_stream_start += chunking_overhead
            if self.flags.crc32:
                # Also skip the corresponding StreamingItem's fields after the contents.
                self._skip_bytes_since_stream_start += 4

        return item

    def open_item_reader(self, item):
        # TODO: use an fdslicer instead of re-opening the input file.
        f = open(self._archive_path, "rb")
        try:
            f.seek(item._stream_start)
            if self.flags.compression:
                decompressor = Decompressor()
            else:
                decompressor = None # Appease pylint
            skip_bytes = item._skip_bytes_until_contents
            while skip_bytes > 0:
                assert self.flags.compression, "skip_bytes is always 0 for no-compression archives"
                size = min(skip_bytes, default_chunk_size)
                skipped_buf = _read_from_decompressor(decompressor, f, size)
                skip_bytes -= len(skipped_buf)
            return ItemReader(self.flags, decompressor, f, item.file_size)
        except:
            f.close()
            raise

class StreamingItem:
    def __init__(self, file_type, file_name_str, streaming_crc32_so_far):
        self.file_type = file_type
        self.file_name_str = file_name_str
        self.streaming_crc32 = streaming_crc32_so_far
        self._predicted_index_item = IndexItem(0, 0, file_type, file_name_str, 0)
        self.done = False

class IndexItem:
    def __init__(self, jump_location, file_size, file_type, file_name_str, contents_crc32):
        self.jump_location = jump_location
        self.file_size = file_size
        self.file_type = file_type
        self.file_name_str = file_name_str
        self.contents_crc32 = contents_crc32

class ItemReader:
    def __init__(self, flags, decompressor, file, file_size):
        self.done = False
        self.flags = flags
        if self.flags.compression:
            self._decompressor = decompressor
        self._input = file
        self._remaining_bytes = file_size
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self._input.close()
        if self.flags.compression:
            self._decompressor = None
    def read_chunk(self):
        size = min(self._remaining_bytes, 0xffff)
        if self.flags.streaming:
            # Also read through the chunk_size.
            size += 2

        if self.flags.compression:
            buf = _read_from_decompressor(self._decompressor, self._input, size)
        else:
            buf = self._input.read(size)
            if len(buf) < size: raise MalformedInputError("unexpected EOF")

        if self.flags.streaming:
            # Drop the chunk_size.
            buf = buf[2:]

        self._remaining_bytes -= len(buf)
        if self._remaining_bytes == 0:
            self.done = True

        return buf

# MAINTAINER NOTE: I originally tried using a base class for these common methods,
# but then pytlint got confused about undefined symbols. OOP considered harmful.
def _validate_archive_path(name):
    try:
        name_str = name.decode("utf8")
        if validate_archive_path(name_str) != name:
            raise InvalidArchivePathError
    except (UnicodeDecodeError, InvalidArchivePathError):
        raise MalformedInputError("invalid name found in archive: " + repr(name)) from None
    return name_str

def _validate_archive_footer(archive_footer):
    """ validates footer_checksum and footer_signature and returns index_region_location """
    if archive_footer[-3:] != footer_signature: raise MalformedInputError("archive footer signature not found. archive truncated?")
    documented_footer_checksum = archive_footer[-4]
    index_region_location_buf = archive_footer[-12:-4]
    calculated_footer_checksum = 0xFF & sum(index_region_location_buf)
    if documented_footer_checksum != calculated_footer_checksum:
        raise MalformedInputError("footer checksum failed. calculated: {}, documented: {}".format(calculated_footer_checksum, documented_footer_checksum))
    (index_region_location,) = struct.unpack("<Q", index_region_location_buf)
    return index_region_location

def _read_from_decompressor(decompressor, file, decompressed_len, *, compressed_read_limit=None, allow_eof=False, unused_data_from_previous_stream=None):
    result = b''
    while True:
        remaining = decompressed_len - len(result)
        if remaining == 0:
            # MAINTAINER NOTE: While the file.read() and BZ2Decompressor API treat -1 as infinity,
            # the zlib.Decompress API treats 0 as infinity, so we can't allow this value to flow through here.
            break

        # Note that you have to check EOF first, as the zlib.Decompress object leaves junk in the other fields once EOF has been hit.
        if decompressor.eof: break

        if unused_data_from_previous_stream:
            result += decompressor.decompress(unused_data_from_previous_stream, remaining)
            unused_data_from_previous_stream = None
            continue
        if decompressor.unconsumed_tail:
            result += decompressor.decompress(decompressor.unconsumed_tail, remaining)
            continue

        # Read more data from the file and feed it to the decompressor.
        if compressed_read_limit != None:
            chunk = file.read(min(compressed_read_limit, default_chunk_size))
            compressed_read_limit -= len(chunk)
        else:
            chunk = file.read(default_chunk_size)
        if len(chunk) == 0:
            # This is going to result in an error.
            break
        #print("input: " + repr(chunk), file=sys.stderr)
        result += decompressor.decompress(chunk, remaining)

    #print("output({},{}): {}".format(decompressed_len, compressed_read_limit, repr(result)), file=sys.stderr)
    if len(result) == decompressed_len: return result
    if allow_eof and len(result) == 0: return b''
    raise MalformedInputError("unexpected end of stream")

def Decompressor():
    return zlib.decompressobj(wbits=-zlib.MAX_WBITS)

if __name__ == "__main__":
    main()
