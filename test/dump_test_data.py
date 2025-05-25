#!/usr/bin/env python3

import sys, os
import json
import zlib

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", required=True, help=
        "directory to write all archives and expected results")
    parser.add_argument("--no-items", action="store_true", help=
        "do not dump the items into a directory. "
        "by default, any test case without an error or maybe_error "
        "gets a directory with the same name (without the .poaf extension) containing the items.")
    parser.add_argument("name", nargs="*", help=
        "to dump specific test cases, give their descriptions. "
        "by default dumps all cases.")
    args = parser.parse_args()

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data.json")) as f:
        test_data = json.load(f)
    canonicalize_test_data(test_data)

    try:
        os.mkdir(args.output)
    except FileExistsError:
        if len(os.listdir(args.output)) != 0:
            sys.exit("--output dir must be empty: " + args.output)

    unused_names = set(args.name) if args.name else None
    for test_case in test_data:
        if unused_names != None:
            try:
                unused_names.remove(test_case["description"])
            except KeyError:
                continue
        with open(os.path.join(args.output, test_case["description"] + ".poaf"), "wb") as f:
            f.write(test_case["contents"])
        if args.no_items or "error" in test_case or "maybe_error" in test_case:
            continue
        # Dump items.
        out_dir = os.path.join(args.output, test_case["description"])
        os.mkdir(out_dir)
        for item in test_case["items"]:
            filename = os.path.join(out_dir, item["name"])
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            if item["type"] in (0, 1): # regular file, posix executable
                with open(filename, "wb") as f:
                    f.write(item["contents"])
                if item["type"] == 1:
                    # chmod +x
                    mode = os.stat(filename).st_mode & 0o777
                    mode |= (mode & 0o444) >> 2
                    os.chmod(filename, mode)
            elif item["type"] == 2: # empty dir
                os.makedirs(filename, exist_ok=True)
            elif item["type"] == 3: # symlink
                os.symlink(item["symlink_target"], filename)

def canonicalize_test_data(test_data):
    for test_case in test_data:
        test_case["contents"] = from_sliced_hex(test_case["contents"])
        for item in test_case.get("items", []):
            if "compressed_name" in item:
                item["name"] = zlib.decompress(from_sliced_hex(item["compressed_name"]), wbits=-zlib.MAX_WBITS).decode("utf8")
                del item["compressed_name"]
            if "compressed_contents" in item:
                item["contents"] = zlib.decompress(from_sliced_hex(item["compressed_contents"]), wbits=-zlib.MAX_WBITS)
                del item["compressed_contents"]
            elif "contents" in item:
                item["contents"] = from_sliced_hex(item["contents"])
def from_sliced_hex(a):
    return b"".join(bytes.fromhex(x) for x in a)

if __name__ == "__main__":
    main()
