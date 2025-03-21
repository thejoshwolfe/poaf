#!/usr/bin/env python3

import zlib
import struct, stat
import os, re
import tempfile, shutil

from common import *

def main():
    import argparse
    parser = argparse.ArgumentParser()

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--no-index", action="store_const", const=STRUCTURE_STREAM_ONLY, dest="structure", default=STRUCTURE_BOTH, help=
        "Optimize the archive for streaming reading, omitting the Index Region.")
    group.add_argument("--no-streaming", action="store_const", const=STRUCTURE_INDEX_ONLY, dest="structure", help=
        "Optimize the archive for random-access in-place reading, omitting the inline metadata in the Data Region.")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--compress", choices=["none", "deflate"], default="deflate", help=
        "Specify the compression method. Default is --compress=deflate.")
    group.add_argument("-z", "--deflate", action="store_const", const="deflate", dest="compress", help=
        "Equivalent to --compress=deflate. This is the default.")
    group.add_argument("-0", "--no-compression", action="store_const", const="none", dest="compress", help=
        "Equivalent to --compress=none.")

    parser.add_argument("--crc32", action="store_true")
    parser.add_argument("--sha256", action="store_true")

    parser.add_argument("-b", "--backup", action="store_true", help=
        "Include extended file system metadata suitable for backups.")

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
        compression_method=args.compress,
        structure         =args.structure,
        crc32             =args.crc32,
        sha256            =args.sha256,
    )

    with Writer(
        flags=flags,
        is_backup=args.backup,
        root=args.root,
        output_path=args.output,
        stream_split_threshold=args.stream_split_threshold,
    ) as writer:
        for file in args.files:
            writer.add(file)

class Writer:
    def __init__(self, flags, is_backup, root, output_path, stream_split_threshold):
        self.flags = flags
        self.is_backup = is_backup
        self.root = root

        if self.flags.crc32() or self.flags.sha256(): raise NotImplementedError
        if is_backup: raise NotImplementedError
        self.checksums_size = 0

        archive_metadata = b'\x00\x00'

        self._output = open(output_path, "wb")
        try:
            # ArchiveHeader
            archive_header = archive_signature + bytes([self.flags.flags])
            assert len(archive_header) == archive_header_size
            self._output.write(archive_header)

            # Data Region
            self._start_stream()
            if self.flags.streaming():
                # ArchiveMetadata
                self._write(archive_metadata)

            if self.flags.index():
                if self.flags.no_compression():
                    self.stream_split_threshold = 0
                else:
                    self.stream_split_threshold = stream_split_threshold
                # Start the index
                self._index_tmpfile = tempfile.TemporaryFile()
                try:
                    if self.flags.no_compression(): pass
                    elif self.flags.deflate():
                        self._index_compressor = Compressor()
                    else: assert False
                    # ArchiveMetadata
                    self._write_to_index(archive_metadata)
                except:
                    self._index_tmpfile.close()
                    raise
        except:
            self._output.close()
            raise

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()

    def add(self, input_path):
        try:
            input_path, archive_path = input_path.rsplit("->", 1)
        except ValueError:
            archive_path = os.path.relpath(input_path, self.root)
        name = validate_archive_path(archive_path)

        # Compute metadata.
        st = os.stat(input_path, follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode): raise NotImplementedError("TODO: non-file: " + input_path)
        file_size = st.st_size
        item_metadata = b''

        # Write header.
        if self.flags.streaming():
            self._write(
                item_signature +
                struct.pack("<HHQ",
                    len(name),
                    len(item_metadata),
                    file_size,
                ) +
                name +
                item_metadata
            )

        # Write contents.
        if self.flags.index():
            if file_size != 0:
                previous_stream_compressed_size = self._maybe_split_stream()
            else:
                # When file_size is 0, a stream split is not allowed.
                previous_stream_compressed_size = 0
        with open(input_path, "rb") as f:
            buf_size = 0x4000
            while True:
                buf = f.read(buf_size)
                if len(buf) == 0: break
                self._write(buf)

        # Write checksums.
        checksums = b''
        assert len(checksums) == self.checksums_size
        if self.flags.streaming():
            self._write(checksums)

        # Write index
        if self.flags.index():
            # IndexItem
            self._write_to_index(
                checksums +
                struct.pack("<QHHQ",
                    previous_stream_compressed_size,
                    len(name),
                    len(item_metadata),
                    file_size,
                ) +
                name +
                item_metadata
            )

    def close(self):
        if self.flags.streaming() and self.flags.index() and not self.flags.compression_method_supports_eof():
            # DataRegionSentinel
            self._write(
                item_signature +
                struct.pack("<HHQ", 0, 0, 0)
            )
        # End the Data Region
        if self.flags.no_compression(): pass
        elif self.flags.deflate():
            self._output.write(self._compressor.flush())
            self._compressor = None
        else: assert False

        if self.flags.index():
            # Index Region.
            data_region_compressed_size = self._output.tell() - archive_header_size
            if self.flags.no_compression(): pass
            elif self.flags.deflate():
                self._index_tmpfile.write(self._index_compressor.flush())
                self._index_compressor = None
            else: assert False
            self._index_tmpfile.seek(0)
            shutil.copyfileobj(self._index_tmpfile, self._output)
            self._index_tmpfile.close()

            # ArchiveFooter.
            checksums = b''
            assert len(checksums) == self.checksums_size
            self._output.write(
                checksums +
                struct.pack("<Q", data_region_compressed_size) +
                footer_signature
            )
        # Done
        self._output.close()

    def _write(self, buf):
        if self.flags.no_compression():
            self._output.write(buf)
        elif self.flags.deflate():
            self._output.write(self._compressor.compress(buf))
        else: assert False
    def _write_to_index(self, buf):
        if self.flags.no_compression():
            self._index_tmpfile.write(buf)
        elif self.flags.deflate():
            self._index_tmpfile.write(self._index_compressor.compress(buf))
        else: assert False

    def _maybe_split_stream(self):
        if self._output.tell() - self._stream_start < self.stream_split_threshold:
            # Too small to split yet.
            return 0
        # Split the stream.
        if self.flags.no_compression(): pass
        elif self.flags.deflate():
            self._output.write(self._compressor.flush())
        else: assert False
        previous_stream_compressed_size = self._output.tell() - self._stream_start
        self._start_stream()
        return previous_stream_compressed_size
    def _start_stream(self):
        if self.flags.no_compression(): pass
        elif self.flags.deflate():
            self._compressor = Compressor()
        else: assert False
        if self.flags.index():
            self._stream_start = self._output.tell()

def Compressor():
    return zlib.compressobj(wbits=-zlib.MAX_WBITS)

if __name__ == "__main__":
    main()
