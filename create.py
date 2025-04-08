#!/usr/bin/env python3

import zlib
import struct, stat
import os, re
import tempfile, shutil

from common import *

def main():
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument("--no-index", action="store_true", help=
        "Optimize the archive for streaming reading, omitting the Index Region.")
    parser.add_argument("--no-streaming", action="store_true", help=
        "Optimize the archive for random-access in-place reading, omitting the inline metadata in the Data Region.")

    parser.add_argument("-0", "--no-compression", action="store_true", help=
        "Disable DEFLATE compression.")
    parser.add_argument("--no-crc32", action="store_true", help=
        "Disable CRC32 checksums.")

    parser.add_argument("--stream-split-threshold", type=int, default=0x10000, help=
        "The minimum number of compressed bytes between stream splits to enable random-access jumping from the index.")

    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--root", default=".", help=
        "See 'files'. Default is the current working directory.")
    parser.add_argument("files", nargs="*", help=
        "Each file argument may contain '->' followed by the path in the archive it will have. "
        "The last occurrence of '->' delimits the argument, which might be relevant if the host path actually contains a '->' string. "
        "If an explicit archive path is not given, the file's path relative to --root (default cwd) is the archive path, "
        "in which case the archive path must not be outside the --root.")

    args = parser.parse_args()

    flags = FeatureFlags.from_values(
        compression=not args.no_compression,
        crc32=      not args.no_crc32,
        streaming=  not args.no_streaming,
        index=      not args.no_index,
    )

    with Writer(
        flags=flags,
        root=args.root,
        output_path=args.output,
        stream_split_threshold=args.stream_split_threshold,
    ) as writer:
        for file in args.files:
            writer.add(file)

class Writer:
    def __init__(self, flags, root, output_path, stream_split_threshold):
        self.flags = flags
        self.root = root

        self._output = open(output_path, "wb")
        try:
            # ArchiveHeader
            archive_header = archive_signature + bytes([self.flags.value()])
            self._output.write(archive_header)

            # Data Region
            self._start_stream()

            if self.flags.index:
                if self.flags.compression:
                    self.stream_split_threshold = stream_split_threshold
                # Start the index
                if self.flags.crc32:
                    self._index_crc32 = 0
                self._index_tmpfile = tempfile.TemporaryFile()
                try:
                    if self.flags.compression:
                        self._index_compressor = Compressor()
                except:
                    self._index_tmpfile.close()
                    raise
        except:
            self._output.close()
            raise

    def __enter__(self):
        return self
    def __exit__(self, *args):
        try:
            self.close()
        except:
            try:
                if self._index_tmpfile != None:
                    self._index_tmpfile.close()
            finally:
                self._output.close()
            raise

    def add(self, input_path):
        try:
            input_path, archive_path = input_path.rsplit("->", 1)
        except ValueError:
            archive_path = os.path.relpath(input_path, self.root)
        name = validate_archive_path(archive_path)

        # Compute metadata.
        st = os.stat(input_path, follow_symlinks=False)
        if stat.S_ISREG(st.st_mode):
            if st.st_mode & 0o111:
                file_type = FILE_TYPE_POSIX_EXECUTABLE
            else:
                file_type = FILE_TYPE_NORMAL_FILE
        elif stat.S_ISDIR(st.st_mode):
            file_type = FILE_TYPE_DIRECTORY
        elif stat.S_ISLNK(st.st_mode):
            file_type = FILE_TYPE_SYMLINK
        else:
            raise NotImplementedError("obscure file type: " + input_path)
        type_and_name_size = (file_type << 14) | len(name)

        if self.flags.streaming:
            # Write StreamingItem pre-contents fields.
            out_buf = (
                item_signature +
                struct.pack("<H", type_and_name_size) +
                name
            )
            self._write(out_buf)
            if self.flags.crc32:
                streaming_crc32 = zlib.crc32(out_buf)

        # Compute jump_location and possibly split compression stream.
        if self.flags.index:
            if not self.flags.compression:
                # All jump locations are set without compression enabled.
                jump_location = self._output.tell()
            else:
                # We might want to split here.
                if self._output.tell() - self._stream_start < self.stream_split_threshold:
                    # Nah, not yet.
                    jump_location = 0
                else:
                    # Yes, split the stream.
                    self._output.write(self._compressor.flush())
                    jump_location = self._output.tell() # Note, have to re-tell() after the above flush()
                    self._start_stream()

        # Contents
        file_size = 0
        if self.flags.index:
            if self.flags.crc32:
                contents_crc32 = 0
        with open(input_path, "rb") as f:
            while True:
                buf = f.read(0xffff)
                if self.flags.streaming:
                    # Chunked encoding
                    out_buf = (
                        struct.pack("<H", len(buf)) +
                        buf
                    )
                    if self.flags.crc32:
                        streaming_crc32 = zlib.crc32(out_buf, streaming_crc32)
                else:
                    out_buf = buf
                self._write(out_buf)

                file_size += len(buf)
                if self.flags.index:
                    if self.flags.crc32:
                        contents_crc32 = zlib.crc32(buf, contents_crc32)

                if len(buf) < 0xffff: break

        # StreamingHeader fields after the contents
        if self.flags.streaming and self.flags.crc32:
            self._write(struct.pack("<L", streaming_crc32))

        # IndexItem
        if self.flags.index:
            if self.flags.crc32:
                contents_crc32_buf = struct.pack("<L", contents_crc32)
            else:
                contents_crc32_buf = b""
            out_buf = (
                contents_crc32_buf +
                struct.pack("<QQH",
                    jump_location,
                    file_size,
                    type_and_name_size,
                ) +
                name
            )
            self._write_to_index(out_buf)
            if self.flags.crc32:
                self._index_crc32 = zlib.crc32(out_buf, self._index_crc32)

    def close(self):
        if self.flags.streaming and self.flags.index and not self.flags.compression:
            # StreamingSentinel
            self._write(
                item_signature +
                struct.pack("<H", 0)
            )
        # End the Data Region
        if self.flags.compression:
            self._output.write(self._compressor.flush())
            self._compressor = None

        if self.flags.index:
            # Index Region.
            index_region_location = self._output.tell()
            if self.flags.compression:
                self._index_tmpfile.write(self._index_compressor.flush())
                self._index_compressor = None
            self._index_tmpfile.seek(0)
            shutil.copyfileobj(self._index_tmpfile, self._output)
            self._index_tmpfile.close()
            self._index_tmpfile = None

            # ArchiveFooter.
            if self.flags.crc32:
                index_crc32_buf = struct.pack("<L", self._index_crc32)
            else:
                index_crc32_buf = b""
            index_region_location_buf = struct.pack("<Q", index_region_location)
            footer_checksum = bytes([0xFF & sum(index_region_location_buf)])
            self._output.write(
                index_crc32_buf +
                index_region_location_buf +
                footer_checksum +
                footer_signature
            )
        # Done
        self._output.close()

    def _write(self, buf):
        if self.flags.compression:
            self._output.write(self._compressor.compress(buf))
        else:
            self._output.write(buf)
    def _write_to_index(self, buf):
        if self.flags.compression:
            self._index_tmpfile.write(self._index_compressor.compress(buf))
        else:
            self._index_tmpfile.write(buf)

    def _start_stream(self):
        if self.flags.compression:
            self._compressor = Compressor()
            if self.flags.index:
                self._stream_start = self._output.tell()

def Compressor():
    return zlib.compressobj(wbits=-zlib.MAX_WBITS)

if __name__ == "__main__":
    main()
