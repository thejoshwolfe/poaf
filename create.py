#!/usr/bin/env python3

import zlib
import struct, stat
import os, re
import tempfile, shutil

def main():
    import argparse
    parser = argparse.ArgumentParser()

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--no-index", action="store_const", const="stream-only", dest="structure", default="both", help=
        "Optimize the archive for streaming reading, omitting the Index Region.")
    group.add_argument("--no-inline", action="store_const", const="index-only", dest="structure", help=
        "Optimize the archive for random-access in-place reading, omitting the inline metadata in the Data Region.")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--compress", choices=["none", "deflate"], default="deflate", help=
        "Specify the compression method. Default is --compress=deflate.")
    group.add_argument("-z", "--deflate", action="store_const", const="deflate", dest="compress", help=
        "Equivalent to --compress=deflate. This is the default.")
    group.add_argument("-0", action="store_const", const="none", dest="compress", help=
        "Equivalent to --compress=none.")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--checksum", choices=["none", "crc32", "sha256"], default="none", help=
        "Specify the checksum algorithm. Default is --checksum=none.")
    group.add_argument("--crc32", action="store_const", const="crc32", dest="checksum", help=
        "Equivalent to --checksum=crc32.")
    group.add_argument("--sha256", action="store_const", const="sha256", dest="checksum", help=
        "Equivalent to --checksum=sha256.")

    parser.add_argument("-b", "--backup", action="store_true", help=
        "Include extended file system metadata suitable for backups.")

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
        structure=args.structure,
        compression=args.compress,
        checksum=args.checksum,
        is_backup=args.backup,
        root=args.root,
        output_path=args.output,
    ) as writer:
        for file in args.files:
            writer.add(file)

archive_magic_number = b'\xbe\xf6\xfc\xf1' # TODO: the other ones.
item_magic_number = b'\xdc\xac\xa9\xdc'
footer_magic_number = b'\xb6\xee\xe9\xcf'

class Writer:
    def __init__(self, structure, compression, checksum, is_backup, root, output_path):
        self.structure = structure
        self.compression = compression
        self.checksum = checksum
        self.is_backup = is_backup
        self.root = root
        self.flush_threshold = 0x10000

        if structure != "both": raise NotImplementedError
        if compression != "deflate": raise NotImplementedError
        if checksum != "none": raise NotImplementedError
        if is_backup: raise NotImplementedError

        self._compressor = Compressor()
        self._written_since_last_optional_flush = 0

        self._output = open(output_path, "wb")
        try:
            self._output.write(archive_magic_number)
            # TODO: ArchiveMetadata

            # Start the index
            self._index_tmpfile = tempfile.TemporaryFile()
            try:
                self._index_compressor = Compressor()
                # TODO: ArchiveMetadata
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

        # Compute header.
        st = os.stat(input_path, follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode): raise NotImplementedError("TODO: non-file: " + input_path)
        file_size = st.st_size
        header_metadata = b''
        footer_metadata_size = 0

        # Write header.
        offset = self._optional_flush()
        self._write(
            item_magic_number +
            struct.pack("<HHQB",
                len(name),
                len(header_metadata),
                file_size,
                footer_metadata_size,
            ) +
            name +
            header_metadata
        )

        # Write contents.
        with open(input_path, "rb") as f:
            buf_size = 0x4000
            while True:
                buf = f.read(buf_size)
                if len(buf) == 0: break
                self._write(buf)

        # Write footer.
        footer_metadata = b''
        assert len(footer_metadata) == footer_metadata_size
        self._write(footer_metadata)

        # Write index
        self._write_to_index(
            struct.pack("<QHHQB",
                offset,
                len(name),
                len(header_metadata),
                file_size,
                footer_metadata_size,
            ) +
            name +
            header_metadata +
            footer_metadata
        )

    def close(self):
        # DataRegionSentinel
        self._write(
            item_magic_number +
            struct.pack("<HHQ", 0, 0, 0)
        )
        self._output.write(self._compressor.flush())
        self._compressor = None

        # Index Region.
        index_offset = self._output.tell()
        self._index_tmpfile.write(self._index_compressor.flush())
        self._index_compressor = None
        self._index_tmpfile.seek(0)
        shutil.copyfileobj(self._index_tmpfile, self._output)
        self._index_tmpfile.close()

        # Write footer.
        self._output.write(
            struct.pack("<Q", index_offset) +
            footer_magic_number
        )
        # Done
        self._output.close()

    def _write(self, buf):
        out_buf = self._compressor.compress(buf)
        self._output.write(out_buf)
        self._written_since_last_optional_flush += len(out_buf)
    def _write_to_index(self, buf):
        self._index_tmpfile.write(self._index_compressor.compress(buf))
    def _optional_flush(self):
        if self._written_since_last_optional_flush < self.flush_threshold: return 0
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
