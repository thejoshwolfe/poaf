#!/usr/bin/env python3

import sys, os
import struct
import zlib
import tempfile

from common import *
from file_slice import FileSlice

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("-x", "--extract", metavar="DIR", help=
        "Extract entire archive to the given directory.")
    parser.add_argument("--no-streaming-fallback", help=
        "When attempting to list the index or extract an explicit selection of items, "
        "fail if the archive does not include an index. "
        "The default behavior is to fallback to streaming the whole archive.")
    parser.add_argument("items", nargs="*", help=
        "If specified, only extracts the given items.")
    args = parser.parse_args()

    want_every_item = not args.items
    want_contents = bool(args.extract)
    prefer_index = not want_every_item or not want_contents

    specific_items = set(args.items)
    found_items = set()
    with open_path(args.archive, prefer_index, args.no_streaming_fallback) as reader:
        for item in reader:
            if len(specific_items) == 0:
                # Handle every item.
                pass
            elif item.file_name_str in specific_items:
                # Handle this item.
                found_items.add(item.file_name_str)
            else:
                # Skip this item.
                reader.skip_item(item)
                continue

            if args.extract:
                # Extract.
                reader.open_item(item)
                extract_item(args.extract, reader, item)
            else:
                # Just list.
                reader.skip_item(item)
                print(item.file_name_str)

    missing_items = specific_items - found_items
    if len(missing_items) > 0:
        sys.exit("\n".join([
            "ERROR: item not found in archive: " + name
            for name in sorted(missing_items)
        ]))

def extract_item(dir, reader, item):
    # Implicit ancestors directories
    i = item.file_name_str.find("/")
    while i != -1:
        ancestor = item.file_name_str[:i]
        i = item.file_name_str.find("/", i)
        ancestor_dir = os.path.join(dir, ancestor.replace("/", os.path.sep))
        if not os.path.isdir(ancestor_dir):
            os.mkdir(ancestor_dir) # an error here means this is already a file or symlink.

    # File contents
    file_name_path = os.path.join(dir, item.file_name_str.replace("/", os.path.sep))
    if item.file_type == FILE_TYPE_DIRECTORY:
        if not os.path.isdir(file_name_path):
            os.mkdir(file_name_path) # an error here means this is already a file or symlink.
    elif item.file_type == FILE_TYPE_SYMLINK:
        # Validation has already been done on the symlink target via validate_archive_path().
        os.symlink(item.symlink_target, file_name_path)
    else:
        # Pump contents of regular file.
        with open(file_name_path, "wb") as output:
            while not item.done:
                output.write(reader.read_from_item(item))
        if item.file_type == FILE_TYPE_POSIX_EXECUTABLE:
            # chmod posix executable bits.
            mode = os.stat(file_name_path).st_mode
            # Respect whatever umask limited the permissions on create.
            # Only eneable x where r is already enabled.
            mode |= (mode & 0o444) >> 2
            os.chmod(file_name_path, mode)

def open_path(archive_path, prefer_index=True, require_index=False):
    if not prefer_index: require_index = False
    file = open(archive_path, "rb")
    try:
        return reader_for_file(file, prefer_index, require_index)
    except:
        file.close()
        raise
def reader_for_file(file, prefer_index=True, require_index=False):
    # ArchiveHeader
    streaming_enabled, index_enabled = validate_archive_header(file.read(4))

    seekable = file.seekable()
    if require_index:
        if not index_enabled:
            raise IncompatibleInputError("archive does not have the index enabled")
        if not seekable:
            raise IncompatibleInputError("archive file does not support seeking")

    if (prefer_index and index_enabled and seekable) or not streaming_enabled:
        return IndexReader(file, streaming_enabled)
    else:
        return StreamingReader(file, index_enabled)

default_chunk_size = 0x4000

class EmptyReader:
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def __iter__(self): return self
    def __next__(self): return self.next()

    # Overridable
    def close(self): pass
    def next(self): raise StopIteration
    def open_item(self, item): pass
    def skip_item(self, item): pass

class StreamingReader(EmptyReader):
    def __init__(self, file, index_enabled, validate_index=True):
        self._input = file
        self.index_enabled = index_enabled

        self._decompressor = Decompressor()
        self.validating_index = validate_index and self.index_enabled
        if self.validating_index:
            self._index_tmpfile = tempfile.TemporaryFile()
            self._index_crc32 = 0

        self._current_item = None

    def close(self):
        self._decompressor = None
        try:
            if self.validating_index:
                self._index_tmpfile.close()
        finally:
            self._input.close()

    def next(self):
        if self._current_item != None: raise ValueError("use skip_item() or call read_from_item() until done")

        # StreamingItem
        buf = self._read(4, allow_eof=True)
        if len(buf) == 0:
            self._done_reading_data_region()
            raise StopIteration

        if buf[0:2] != item_signature: raise MalformedInputError("item signature not found")
        (type_and_name_size,) = struct.unpack("<H", buf[2:])
        file_type, name_size = type_and_name_size >> 14, type_and_name_size & 0x3FFF

        # Read the rest of the StreamingItem.
        name = self._read(name_size)
        file_name_str = _validate_archive_path(name)

        streaming_crc32 = zlib.crc32(buf)
        streaming_crc32 = zlib.crc32(name, streaming_crc32)

        item = StreamingItem(file_type, file_name_str, streaming_crc32)

        self._current_item = item
        if item.file_type in (FILE_TYPE_DIRECTORY, FILE_TYPE_SYMLINK):
            # Read the contents immediately. It's always bounded size.
            self.read_from_item(item)
        return item

    def read_from_item(self, item, size_limit=0xFFFFFFFFFFFFFFFF):
        if self._current_item != item: raise ValueError("that's not the current item.")

        # Check for stream split before StreamingItem chunked contents.
        allow_eof = item._predicted_index_item.file_size == 0
        chunk_size_buf = self._read(2, allow_eof=allow_eof)
        if len(chunk_size_buf) == 0:
            # Found a stream split.
            assert self._decompressor.eof
            unused_data = self._decompressor.unused_data
            unused_data_len = len(unused_data)
            if self.index_enabled:
                item._predicted_index_item.jump_location = self._input.tell() - unused_data_len
            self._decompressor = Decompressor()

            # Try again
            chunk_size_buf = self._read(2, unused_data_from_previous_stream=unused_data)

        # StreamingItem chunked contents
        (chunk_size,) = struct.unpack("<H", chunk_size_buf)
        buf = self._read(chunk_size)
        item.done = len(buf) < 0xFFFF

        # Special handling for directory and symlink contents.
        if item.file_type == FILE_TYPE_DIRECTORY:
            if chunk_size > 0: raise MalformedInputError("directory items must have 0-length contents")
        elif item.file_type == FILE_TYPE_SYMLINK:
            if chunk_size > 4095: raise MalformedInputError("symlink length exceeds 4095")
            try:
                item.symlink_target = buf.decode("utf8")
            except UnicodeDecodeError as e:
                raise MalformedInputError("symlink target invalid utf8", e)
            try:
                validate_archive_path(item.symlink_target, file_name_of_symlink=item.file_name_str)
            except InvalidArchivePathError as e:
                raise MalformedInputError("illegal symlink target", e)

        # Track file size
        item._predicted_index_item.file_size += len(buf)
        if item._predicted_index_item.file_size > size_limit: raise ItemContentsTooLongError

        # Compute crc32
        item.streaming_crc32 = zlib.crc32(chunk_size_buf, item.streaming_crc32)
        item.streaming_crc32 = zlib.crc32(buf,            item.streaming_crc32)
        if self.index_enabled:
            item._predicted_index_item.contents_crc32 = zlib.crc32(buf, item._predicted_index_item.contents_crc32)

        if item.done:
            self._current_item = None

            # StreamingItem streaming_crc32
            (documented_streaming_crc32,) = struct.unpack("<L", self._read(4))
            if item.streaming_crc32 != documented_streaming_crc32:
                raise MalformedInputError("streaming_crc32 check failed. calculated: {}, documented: {}".format(item.streaming_crc32, documented_streaming_crc32))

            # IndexItem
            if self.validating_index:
                index_item = item._predicted_index_item
                name = index_item.file_name_str.encode("utf8")
                type_and_name_size = (index_item.file_type << 14) | len(name)
                self._index_tmpfile.write((
                    struct.pack("<LQQH",
                        index_item.contents_crc32,
                        index_item.jump_location,
                        index_item.file_size,
                        type_and_name_size,
                    ) +
                    name
                ))
        return buf

    def skip_item(self, item):
        while not item.done:
            self.read_from_item(item)

    def _done_reading_data_region(self):
        if not self.index_enabled:
            # Ensure we hit EOF.
            if not (self._decompressor.eof and len(self._decompressor.unconsumed_tail) == 0): raise MalformedInputError("expected EOF after Data Region")
            if len(self._input.read(1)) != 0: raise MalformedInputError("expected EOF after Data Region")
            # That's all there is to check.
            return

        if not self.validating_index:
            # We're choosing not to validate any more of the archive.
            return

        index_size_remaining = self._index_tmpfile.tell()
        self._index_tmpfile.seek(0)

        # Start a new decompression stream.
        unused_data = self._decompressor.unused_data
        unused_data_len = len(unused_data)
        self._decompressor = Decompressor()
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

        # Make sure we're at the end of the compression stream.
        extra = self._read(1, unused_data_from_previous_stream=unused_data, allow_eof=True)
        if len(extra) != 0: raise MalformedInputError("Index Region compression stream too long")
        unused_data = self._decompressor.unused_data

        # Validate the ArchiveFooter.
        archive_footer_size = 16
        # Ask for 1 too many bytes to make sure we hit EOF.
        documented_archive_footer = unused_data + self._input.read(max(0, archive_footer_size - len(unused_data) + 1))
        if len(documented_archive_footer) > archive_footer_size: raise MalformedInputError("expected EOF after ArchiveFooter")
        if len(documented_archive_footer) < archive_footer_size: raise MalformedInputError("unexpected EOF")

        # Compute what we know the ArchiveFooter should be and compare it all at once.
        index_region_location_buf = struct.pack("<Q", index_region_location)
        footer_checksum = bytes([0xFF & sum(index_region_location_buf)])
        calculated_archive_footer = (
            struct.pack("<L", index_crc32) +
            index_region_location_buf +
            footer_checksum +
            footer_signature
        )

        if documented_archive_footer != calculated_archive_footer: raise MalformedInputError("ArchiveFooter is wrong")

        # Everything's good.

    def _read(self, n, *, allow_eof=False, unused_data_from_previous_stream=None):
        return _read_from_decompressor(self._decompressor, self._input, n, allow_eof=allow_eof, unused_data_from_previous_stream=unused_data_from_previous_stream)

class IndexReader(EmptyReader):
    def __init__(self, file, streaming_enabled):
        self._input = file
        self.streaming_enabled = streaming_enabled

        data_region_start = 4
        self._stream_start = data_region_start
        self._skip_bytes_since_stream_start = 0

        # ArchiveFooter
        self._file_size = self._input.seek(0, os.SEEK_END)
        archive_footer_size = 16
        self.archive_footer_start = self._file_size - archive_footer_size
        if not (4 <= self.archive_footer_start): raise MalformedInputError("unexpected EOF")
        self._input.seek(self.archive_footer_start)
        # archive_footer
        archive_footer = self._input.read(archive_footer_size)

        self.index_region_location = _validate_archive_footer(archive_footer)

        if not (data_region_start <= self.index_region_location < self.archive_footer_start): raise MalformedInputError("index_region_location out of bounds")

        (self.index_crc32,) = struct.unpack("<L", archive_footer[0:4])
        self._calculated_index_crc32 = 0

        # Start the Index Region.
        self._index_file = FileSlice(self._input, self.index_region_location, self.archive_footer_start)
        self._index_decompressor = Decompressor()

    def close(self):
        self._input.close()
        self._index_decompressor = None

    def next(self):
        # IndexItem
        buf = self._read_index(22, allow_eof=True)
        if len(buf) == 0:
            # Make sure we've actually reached the end of the Index Region.
            if self._index_file.start < self._index_file.end:
                raise MalformedInputError("Index Region compression stream ended too early")
            # Done with the Index Region.
            if self._calculated_index_crc32 != self.index_crc32:
                raise MalformedInputError("index_crc32 check failed. calculated: {}, documented: {}".format(self._calculated_index_crc32, self.index_crc32))
            raise StopIteration

        (
            contents_crc32,
            jump_location,
            file_size,
            type_and_name_size,
        ) = struct.unpack("<LQQH", buf)
        file_type, name_size = type_and_name_size >> 14, type_and_name_size & 0x3FFF
        name = self._read_index(name_size)
        file_name_str = _validate_archive_path(name)

        self._calculated_index_crc32 = zlib.crc32(buf, self._calculated_index_crc32)
        self._calculated_index_crc32 = zlib.crc32(name, self._calculated_index_crc32)

        item = IndexItem(jump_location, file_size, file_type, file_name_str, contents_crc32)

        # Compute offset for random access.
        if jump_location > 0:
            # This is a stream split
            self._stream_start = jump_location
            self._skip_bytes_since_stream_start = 0
        elif self.streaming_enabled:
            # Skip the corresponding StreamingItem's fields before the contents.
            self._skip_bytes_since_stream_start += 4 + name_size
        item._stream_start = self._stream_start
        item._skip_bytes_until_contents = self._skip_bytes_since_stream_start

        # For the next item, skip the file_contents of this item.
        self._skip_bytes_since_stream_start += file_size
        if self.streaming_enabled:
            chunking_overhead = 2 * ((file_size // 0xFFFF) + 1)
            self._skip_bytes_since_stream_start += chunking_overhead
            # Also skip the corresponding StreamingItem's fields after the contents.
            self._skip_bytes_since_stream_start += 4

        return item

    def open_item(self, item):
        assert item._contents_file == None, "already open"
        contents_file = FileSlice(self._input, item._stream_start, self.index_region_location)
        decompressor = Decompressor()
        skip_bytes = item._skip_bytes_until_contents
        while skip_bytes > 0:
            size = min(skip_bytes, default_chunk_size)
            skipped_buf = _read_from_decompressor(decompressor, contents_file, size)
            skip_bytes -= len(skipped_buf)
        assert skip_bytes == 0
        item.done = False
        item._contents_file = contents_file
        item._decompressor = decompressor
        item._remaining_bytes = item.file_size

    def _read_index(self, n, *, allow_eof=False):
        # Pump more from the decompressor.
        return _read_from_decompressor(self._index_decompressor, self._index_file, n, allow_eof=allow_eof)

    def read_from_item(self, item):
        assert item._contents_file != None, "call open_item() first"
        size = min(item._remaining_bytes, 0xffff)
        if self.streaming_enabled:
            # Also read through the chunk_size.
            size += 2

        buf = _read_from_decompressor(item._decompressor, item._contents_file, size)

        if self.streaming_enabled:
            # Drop the chunk_size.
            buf = buf[2:]

        item._remaining_bytes -= len(buf)
        if item._remaining_bytes == 0:
            item.done = True
            # Reset in case you want to read it again.
            item._contents_file = None
            item._decompressor = None

        return buf

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
        # Used after opening the item:
        self.done = None
        self._contents_file = None
        self._decompressor = None
        self._remaining_bytes = None


def _validate_archive_path(name):
    try:
        name_str = name.decode("utf8")
        validate_archive_path(name_str)
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

def _read_from_decompressor(decompressor, file, decompressed_len, *, allow_eof=False, unused_data_from_previous_stream=None):
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
        chunk = file.read(default_chunk_size)
        if len(chunk) == 0:
            # This is going to result in an error.
            break
        #print("input: " + repr(chunk), file=sys.stderr)
        result += decompressor.decompress(chunk, remaining)

    #print("output({}): {}".format(decompressed_len, repr(result)), file=sys.stderr)
    if len(result) == decompressed_len: return result
    if allow_eof and decompressor.eof and len(result) == 0: return b''
    raise MalformedInputError("unexpected end of stream")

def Decompressor():
    return zlib.decompressobj(wbits=-zlib.MAX_WBITS)

if __name__ == "__main__":
    main()
