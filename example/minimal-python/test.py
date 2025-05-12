#!/usr/bin/env python3

import sys, os, stat, subprocess
import zlib
import tempfile
import json

this_dir = os.path.dirname(os.path.abspath(__file__))
repo_dir = os.path.dirname(os.path.dirname(this_dir))
test_dir = os.path.join(repo_dir, "test")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    test_from_data(args.verbose)

def should_skip(test):
    if test.get("error", "") in {
        "IndexItem",
        "ArchiveFooter",
    }:
        return True

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

def test_from_data(verbose):
    with open(os.path.join(test_dir, "test_data.json")) as f:
        test_data = json.load(f)
    canonicalize_test_data(test_data)

    current_group = None
    current_group_count = None
    for test in test_data:
        if verbose:
            print(test["description"] + "...", end="", flush=True)
        else:
            if current_group != test["group"]:
                if current_group != None:
                    print("{0}/{0} pass".format(current_group_count))
                current_group = test["group"]
                print(current_group + "...", end="", flush=True)
                current_group_count = 0
            current_group_count += 1

        if should_skip(test):
            if verbose:
                print("skip")
            continue

        with TemporaryDirectory(prefix="poaf.test.") as dir:
            try:
                run_test(test, dir)
            except:
                if not verbose:
                    print("\n" + test["description"] + "...", end="", flush=True)
                print("", flush=True)
                raise

        if verbose:
            print("pass")
    if not verbose:
        print("{0}/{0} pass".format(current_group_count))

def run_test(test, dir):
    is_error_ok = False
    is_no_error_ok = False
    expected_items = []
    if test.get("error", None) != None:
        is_error_ok = True
    elif test.get("items", None) != None:
        expected_items = test["items"]
        is_no_error_ok = True
        if test.get("maybe_error", None) != None:
            is_error_ok = True
    else: assert False

    #if test["description"] == "many ancestors":
    #    import pdb; pdb.set_trace()
    cmd = [os.path.join(this_dir, "read.py"), "/dev/stdin", "--extract-to", dir]
    process = subprocess.run(cmd, input=test["contents"], capture_output=True)
    if process.returncode != 0:
        if not is_error_ok:
            print(process.stderr.decode("utf8"), end="")
            print(process.stdout.decode("utf8"), end="")
            raise Exception("child process failed")
        return # seems fine.
    else:
        if not is_no_error_ok: raise Exception("should have found an error")
    name_set = set(list_file_names(dir))
    for item in expected_items:
        try:
            name_set.remove(item["name"])
        except KeyError:
            if item["type"] != 2: raise Exception("non-directory entry failed to create: " + item["name"]) from None
        real_path = os.path.join(dir, item["name"])
        st = os.stat(real_path, follow_symlinks=False)
        if item["type"] == 0:
            if not (stat.S_ISREG(st.st_mode) and (st.st_mode & 0o111) == 0): raise Exception("expected regular file: " + item["name"])
        elif item["type"] == 1:
            if not (stat.S_ISREG(st.st_mode) and (st.st_mode & 0o111) != 0): raise Exception("expected posix executable: " + item["name"])
        elif item["type"] == 2:
            if not stat.S_ISDIR(st.st_mode): raise Exception("expected directory: " + item["name"])
        else:
            if not stat.S_ISLNK(st.st_mode): raise Exception("expected symlink: " + item["name"])

        if item["type"] in (0, 1):
            with open(real_path, "rb") as f:
                if item["contents"] != f.read(): raise Exception("wrong contents: " + item["name"])
        elif item["type"] == 3:
            if item["symlink_target"] != os.readlink(real_path): raise Exception("wrong symlink target: " + item["name"])
    if len(name_set) > 0:
        raise Exception("extraneous files: " + ", ".join(sorted(name_set)))

def list_file_names(root):
    for dir, _, _ in os.walk(root):
        # When there are symlinks, the get categorized silently into dirs or files, so those are basically useless to us.
        items = os.listdir(dir)
        for item in items:
            st = os.stat(os.path.join(dir, item), follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode): continue
            yield os.path.relpath(os.path.join(dir, item), root).replace(os.path.sep, "/")
        if len(items) == 0 and not os.path.samefile(root, dir):
            # empty dir is a name
            yield os.path.relpath(dir, root).replace(os.path.sep, "/")

class TemporaryDirectory(tempfile.TemporaryDirectory):
    """
    The same as tempfile.TemporaryDirectory,
    except shells out to rm -rf to do the cleanup.
    During the "many ancestors" test, shutil.rmtree crashes with an OSError "Too many open files",
    due to trying to use the *safe* fd-based traversal that opens all the directories in a vertical stack simultaneously.
    Well it was a nice attempt at safety at least. Time to shell out to old reliable.
    """
    @classmethod
    def _rmtree(cls, name, ignore_errors=False, repeated=False):
        subprocess.run(["rm", "-rf", name], check=not ignore_errors)

if __name__ == "__main__":
    main()
