#!/usr/bin/env python3

import zlib
import struct, stat
import os, re
import tempfile, shutil

from common import *

def main():
    import argparse
    parser = argparse.ArgumentParser()

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

    with Writer(
        root=args.root,
        output_path=args.output,
        stream_split_threshold=args.stream_split_threshold,
    ) as writer:
        for file in args.files:
            writer.add(file)

class Writer:
    def __init__(self, root, output_path, stream_split_threshold):
        self.root = root
        self.stream_split_threshold = stream_split_threshold

        self._output = open(output_path, "wb")
        try:
            # ArchiveHeader
            self._output.write(archive_header)

            # Data Region
            self._start_stream()

            # Start the index
            self._index_crc32 = 0
            self._index_compressor = Compressor()
            self._index_tmpfile = tempfile.TemporaryFile()
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
            # Canonicalize slash direction.
            archive_path = archive_path.replace(os.path.sep, "/")
        try:
            type_code, archive_path = archive_path.split(":", 1)
        except ValueError:
            type_code = None # Infer
        name = validate_archive_path(archive_path)

        # Compute metadata.
        if type_code == None:
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
                raise Exception("obscure file type: " + input_path)
        elif type_code == "f": file_type = FILE_TYPE_NORMAL_FILE
        elif type_code == "x": file_type = FILE_TYPE_POSIX_EXECUTABLE
        elif type_code == "d": file_type = FILE_TYPE_DIRECTORY
        elif type_code == "l": file_type = FILE_TYPE_SYMLINK
        else: raise Exception("unrecognized type code: " + repr(type_code))
        type_and_name_size = (file_type << 14) | len(name)

        # Write DataItem pre-contents fields.
        out_buf = (
            item_signature +
            struct.pack("<H", type_and_name_size) +
            name
        )
        self._write(out_buf)
        streaming_crc32 = zlib.crc32(out_buf)

        # Compute jump_location and possibly split compression stream.
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
        contents_crc32 = 0
        if file_type in (FILE_TYPE_NORMAL_FILE, FILE_TYPE_POSIX_EXECUTABLE):
            with open(input_path, "rb") as f:
                while True:
                    buf = f.read(0xffff)
                    out_buf = (
                        struct.pack("<H", len(buf)) +
                        buf
                    )
                    self._write(out_buf)
                    streaming_crc32 = zlib.crc32(out_buf, streaming_crc32)

                    file_size += len(buf)
                    contents_crc32 = zlib.crc32(buf, contents_crc32)

                    if len(buf) < 0xffff: break

        elif file_type == FILE_TYPE_DIRECTORY:
            out_buf = b"\x00\x00"
            self._write(out_buf)
            streaming_crc32 = zlib.crc32(out_buf, streaming_crc32)
        elif file_type == FILE_TYPE_SYMLINK:
            link_target_str = os.readlink(input_path)
            buf = validate_archive_path(link_target_str, file_name_of_symlink=archive_path)
            out_buf = (
                struct.pack("<H", len(buf)) +
                buf
            )
            self._write(out_buf)
            streaming_crc32 = zlib.crc32(out_buf, streaming_crc32)
            file_size += len(buf)
            contents_crc32 = zlib.crc32(buf, contents_crc32)
        else: assert False

        # DataItem fields after the contents
        self._write(struct.pack("<L", streaming_crc32))

        # IndexItem
        out_buf = (
            struct.pack("<LQQH",
                contents_crc32,
                jump_location,
                file_size,
                type_and_name_size,
            ) +
            name
        )
        self._write_to_index(out_buf)
        self._index_crc32 = zlib.crc32(out_buf, self._index_crc32)

    def close(self):
        # End the Data Region
        self._output.write(self._compressor.flush())
        self._compressor = None

        # Index Region.
        index_region_location = self._output.tell()
        self._index_tmpfile.write(self._index_compressor.flush())
        self._index_compressor = None
        self._index_tmpfile.seek(0)
        shutil.copyfileobj(self._index_tmpfile, self._output)
        self._index_tmpfile.close()
        self._index_tmpfile = None

        # ArchiveFooter.
        index_region_location_buf = struct.pack("<Q", index_region_location)
        footer_checksum = bytes([0xFF & sum(index_region_location_buf)])
        self._output.write(
            struct.pack("<L", self._index_crc32) +
            index_region_location_buf +
            footer_checksum +
            footer_signature
        )

        # Done
        self._output.close()

    def _write(self, buf):
        self._output.write(self._compressor.compress(buf))
    def _write_to_index(self, buf):
        self._index_tmpfile.write(self._index_compressor.compress(buf))

    def _start_stream(self):
        self._compressor = Compressor()
        self._stream_start = self._output.tell()

def Compressor():
    return zlib.compressobj(wbits=-zlib.MAX_WBITS)

if __name__ == "__main__":
    main()
