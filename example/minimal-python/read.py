#!/usr/bin/env python3

import sys, os
import struct
import zlib

from common import validate_file_name

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", metavar="ARCHIVE.poaf")
    parser.add_argument("-x", "--extract-to", required=True)
    args = parser.parse_args()

    root = args.extract_to
    with open(args.archive, "rb") as archive:
        try:
            os.mkdir(root)
        except FileExistsError:
            if len(os.listdir(root)) != 0: sys.exit("ERROR: directory exists and is not empty: " + root)

        # ArchiveHeader
        if archive.read(4) != b"\xBE\xF6\xF0\x9F": raise Exception("not a poaf archive")

        decompressor = zlib.decompressobj(wbits=-zlib.MAX_WBITS)
        # Feed the entire rest of the archive to the decompressor.
        streaming_signature_buf = decompressor.decompress(archive.read(), max_length=2)
        def readFromDecompressor(n):
            if n == 0: return b"" # max_length=0 means infinity in the zlib API.
            buf = decompressor.decompress(decompressor.unconsumed_tail, max_length=n)
            if len(buf) < n: raise Exception("unexpected EOF")
            return buf

        while len(streaming_signature_buf) != 0:
            # DataItem
            if streaming_signature_buf != b"\xDC\xAC": raise Exception("streaming_signature mismatch")
            type_and_name_size_buf = readFromDecompressor(2)
            [type_and_name_size] = struct.unpack("<H", type_and_name_size_buf)
            file_type = type_and_name_size >> 14
            file_name_bytes = readFromDecompressor(type_and_name_size & 0x3fff)
            validate_file_name(file_name_bytes)
            dest_path = os.path.join(root, file_name_bytes.decode("utf8"))

            streaming_crc32 = zlib.crc32(streaming_signature_buf + type_and_name_size_buf + file_name_bytes)

            # DataItem chunk_size and chunk
            chunk_size_buf = decompressor.decompress(decompressor.unconsumed_tail, max_length=2)
            if len(chunk_size_buf) == 0:
                # Compression stream split.
                assert decompressor.eof
                unused_data = decompressor.unused_data
                decompressor = zlib.decompressobj(wbits=-zlib.MAX_WBITS)
                chunk_size_buf = decompressor.decompress(unused_data, max_length=2)
                if len(chunk_size_buf) < 2: raise Exception("unexpected EOF")
            [chunk_size] = struct.unpack("<H", chunk_size_buf)
            chunk = readFromDecompressor(chunk_size)
            streaming_crc32 = zlib.crc32(chunk_size_buf + chunk, streaming_crc32)

            if file_type in (0, 1): # regular file, posix executable
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "xb") as f:
                    while True:
                        f.write(chunk)
                        if chunk_size < 0xffff: break
                        # Next DataItem chunk_size and chunk
                        chunk_size_buf = readFromDecompressor(2)
                        [chunk_size] = struct.unpack("<H", chunk_size_buf)
                        chunk = readFromDecompressor(chunk_size)
                        streaming_crc32 = zlib.crc32(chunk_size_buf + chunk, streaming_crc32)
                if file_type == 1: # posix executable
                    # chmod +x
                    mode = os.stat(dest_path).st_mode & 0o777
                    mode |= (mode & 0o444) >> 2
                    os.chmod(dest_path, mode)
            elif file_type == 2: # directory
                os.makedirs(dest_path, exist_ok=True)
                if chunk_size != 0: raise Exception("directories must have empty contents")
            else: # symlink
                symlink_target_bytes = chunk
                validate_symlink_target(symlink_target_bytes, file_name_bytes)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                os.symlink(symlink_target_bytes.decode("utf8"), dest_path)

            # DataItem.streaming_crc32
            [documented_streaming_crc32] = struct.unpack("<L", readFromDecompressor(4))
            if streaming_crc32 != documented_streaming_crc32: raise Exception("streaming_crc32 mismatch")

            # Next DataItem.streaming_signature or end of Data Region.
            streaming_signature_buf = decompressor.decompress(decompressor.unconsumed_tail, max_length=2)
            if len(streaming_signature_buf) not in (0, 2): raise Exception("unexpected EOF")

        # Now decompressor.unused_data contains the Index Region and the ArchiveFooter,
        # but we ignore those and exit early.

if __name__ == "__main__":
    main()
