#!/usr/bin/env python3

import zlib
import struct, stat
import os, re

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--root", help=
        "See the help for files. Default is the current working directory.")
    parser.add_argument("files", nargs="*", help=
        "Each file argument may contain '->' followed by the path in the archive it will have. "
        "The last occurrence of '->' delimits the argument, which might be relevant if the host path actually contains a '->' string. "
        "If an explicit archive path is not given, the file's path relative to --root (default cwd) is the archive path, "
        "in which case the archive path must not be outside the --root.")
    args = parser.parse_args()

    with Writer(args.root or ".", args.output) as writer:
        for file in args.files:
            writer.add(file)

archive_magic_number = b'\xbe\xf6\xfc\xc3'
item_magic_number = b'\xdc\xac\xa9\xdc'
footer_magic_number = b'\xb6\xee\xe9\xcf'
optional_flush_threshold = 0x10000

class Writer:
    def __init__(self, root, output_path):
        self._root = root
        self._output = open(output_path, "wb")
        self._output.write(archive_magic_number)
        self._compressor = Compressor()
        self._item_headers = []
        self._written_since_last_optional_flush = 0

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()

    def add(self, input_path):
        try:
            input_path, archive_path = input_path.rsplit("->", 1)
        except ValueError:
            archive_path = os.path.relpath(input_path, self._root)
        name = validate_archive_path(archive_path)

        # Compute header.
        st = os.stat(input_path, follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode): raise NotImplementedError("TODO: non-file: " + input_path)
        file_size = st.st_size
        metadata = b''

        # Write header.
        if len(self._item_headers) == 0:
            offset = 4
        else:
            offset = self._optional_flush()
        item_header = (
            struct.pack("<HHQ",
                len(name),
                len(metadata),
                file_size,
            ) +
            name +
            metadata
        )
        self._write(item_magic_number + item_header)
        self._item_headers.append(struct.pack("<Q", offset) + item_header)

        with open(input_path, "rb") as f:
            buf_size = 0x4000
            while True:
                buf = f.read(buf_size)
                if len(buf) == 0: break
                self._write(buf)

    def close(self):
        # Finish data region.
        self._write(
            item_magic_number +
            struct.pack("<HHQ", 0, 0, 0)
        )
        self._output.write(self._compressor.flush())
        self._compressor = Compressor()
        # Begin index region.
        index_offset = self._output.tell()
        for item_header in self._item_headers:
            self._write(item_header)
        # Finish index region.
        self._output.write(self._compressor.flush())
        self._compressor = None
        # Write footer.
        self._output.write(
            struct.pack("<Q", index_offset) +
            footer_magic_number
        )
        # Done
        self._output.close()
        self._item_headers = [] # Free up some memory or something idk.

    def _write(self, buf):
        out_buf = self._compressor.compress(buf)
        self._output.write(out_buf)
        self._written_since_last_optional_flush += len(out_buf)
    def _optional_flush(self):
        if self._written_since_last_optional_flush < optional_flush_threshold: return 0
        self._output.write(self._compressor.flush())
        self._compressor = Compressor()
        self._written_since_last_optional_flush = 0
        return self._output.tell()

def Compressor():
    return zlib.compressobj(wbits=-zlib.MAX_WBITS)

class InvalidArchivePathError(Exception): pass
def validate_archive_path(archive_path):
    # Canonicalize slash direction.
    archive_path = archive_path.replace(os.path.sep, "/")
    if len(archive_path) == 0: raise InvalidArchivePathError("Path must not be empty")
    name = archive_path.encode("utf8")
    segments = name.split(b"/")
    # Catch path traversal.
    if len(segments[0]) == 0: raise InvalidArchivePathError("Path must not be absolute", archive_path)
    if b".." in segments: raise InvalidArchivePathError("Path must not contain '..' segments", archive_path)
    # Forbid non-normalized paths.
    if b"" in segments:   raise InvalidArchivePathError("Path must not contain empty segments", archive_path)
    if b"." in segments:  raise InvalidArchivePathError("Path must not contain '.' segments", archive_path)
    # Windows-friendly characters (also no absolute Windows paths, because of ':'.).
    match = re.search(rb'[\x00-\x1f<>:"|?*]', name)
    if match != None: raise InvalidArchivePathError("Path must not contain special characters [\\x00-\\x1f<>:\"|?*]", archive_path)

    # Check length limits.
    if any(len(segment) > 255 for segment in segments): raise InvalidArchivePathError("Path segments must not be longer than 255 bytes", archive_path)
    if len(segments) > 255: raise InvalidArchivePathError("Path must not contain more than 255 segments", archive_path)
    if len(name) > 32767: raise InvalidArchivePathError("Path must not be longer than 32767 bytes", archive_path)

    return name

if __name__ == "__main__":
    main()
