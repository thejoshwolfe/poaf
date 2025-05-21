#!/usr/bin/env python3

import sys, os, stat
import tempfile, shutil
import io, struct
import zlib

from common import validate_file_name, validate_symlink_target

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", metavar="ARCHIVE.poaf")
    parser.add_argument("files", nargs="*", help="input files")
    args = parser.parse_args()

    with open(args.output, "wb") as out, tempfile.SpooledTemporaryFile(prefix="poaf.index.", max_size=0x10000) as index_file:
        data_compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        index_compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        index_crc32 = 0

        # ArchiveHeader
        out.write(b"\xBE\xF6\xF0\x9F") # archive_signature

        for file in args.files:
            # type_and_name and file_name
            file_name = file.encode("utf8")
            validate_file_name(file_name)
            st = os.stat(file, follow_symlinks=False)
            if stat.S_ISREG(st.st_mode):
                if (st.st_mode & 0o444) == 0:
                    file_type = 0 # regular file
                else:
                    file_type = 1 # posix executable
            elif stat.S_ISDIR(st.st_mode):
                file_type = 2 # directory
            elif stat.S_ISLNK(st.st_mode):
                file_type = 3 # symlink
            else: sys.exit("ERROR: unsupported file type: " + file)
            type_and_name = struct.pack("<H",
                (file_type << 14) | len(file_name) # type_and_name_size
            ) + file_name

            # DataItem
            data_item_buf = io.BytesIO()
            data_item_buf.write(b"\xDC\xAC") # streaming_signature
            data_item_buf.write(type_and_name)

            contents_crc = 0
            file_size = 0
            if file_type in (0, 1): # regular file, posix executable
                with open(file, "rb") as input_file:
                    while True:
                        chunk = input_file.read(0xffff)
                        data_item_buf.write(struct.pack("<H", len(chunk))) # chunk_size
                        data_item_buf.write(chunk) # chunk
                        contents_crc = zlib.crc32(chunk, contents_crc)
                        file_size += len(chunk)
                        if len(chunk) < 0xffff: break
            elif file_type == 2: # directory
                data_item_buf.write(b"\x00\x00") # chunk_size
            else: # symlink
                symlink_target = os.readlink(file).encode("utf8")
                validate_symlink_target(file_name, symlink_target)
                data_item_buf.write(struct.pack("<H", len(symlink_target))) # chunk_size
                data_item_buf.write(symlink_target) # chunk
                contents_crc = zlib.crc32(chunk)
                file_size = len(symlink_target)

            data_item_buf.write(struct.pack("<L", zlib.crc32(data_item_buf.getvalue()))) # streaming_crc32

            # IndexItem
            index_item = (
                struct.pack("<QQL", 0, file_size, contents_crc) # jump_location, file_size, contents_crc32
                + type_and_name # type_and_name_size, file_name
            )
            index_crc32 = zlib.crc32(index_item, index_crc32)

            out.write(data_compressor.compress(data_item_buf.getvalue()))
            index_file.write(index_compressor.compress(index_item))

        out.write(data_compressor.flush())
        index_file.write(index_compressor.flush())

        # Index Region
        index_location = out.tell()
        index_file.seek(0)
        shutil.copyfileobj(index_file, out)

        # ArchiveFooter
        index_location_bytes = struct.pack("<Q", index_location)
        out.write(struct.pack("<L", index_crc32)) # index_crc32
        out.write(index_location_bytes) # index_location
        out.write(bytes([0xff & sum(index_location_bytes)])) # footer_checksum
        out.write(b"\xEE\xE9\xCF") # footer_signature

if __name__ == "__main__":
    main()
