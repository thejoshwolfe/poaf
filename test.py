#!/usr/bin/env python3

# TODO: make a test with a compression stream that can be jumped in from multiple offsets, resulting in overlapping data regions:
#   data = b'\x00\x05\x00\xFA\xFF' + b'\x00\x00\x00\xFF\xFF' + b'\x03\x00'
#   decompress(data) # succeeds
#   decompress(data[5:]) # also succeeds
# This should be result in a streaming reader catching an error with unexpected `jump_location` or something probably.

import os
import subprocess
import tempfile
import itertools
import io

from read import reader_for_file
from common import PoafException
from test_data import data as test_data

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.parse_args()

    test_from_data()
    test_permutations()

def test_from_data():
    for test in test_data:
        print(test["description"] + "...", end="", flush=True)
        run_test(test)
        print("pass")

def run_test(test):
    contents = io.BytesIO(bytes.fromhex(test["contents"]["hex"]))

    expect_error = False
    expected_items = []
    if test["result"] == "error":
        expect_error = True
    elif type(test["result"]) == list:
        expected_items = test["result"]
    else: assert False

    try:
        reader = reader_for_file(contents, prefer_index=False)
        for expected_item, got_item in zip(expected_items, reader, strict=True):
            raise NotImplementedError
    except PoafException as e:
        if not expect_error: raise
    else:
        assert not expect_error

def test_permutations():
    file_name_args = [
        "/dev/null->f:empty_test_file_1.txt",
        "create.py",
        "read.py",
        "/dev/null->f:empty_test_file_2.txt",
        "/dev/null->f:empty_test_file_3.txt",
        "common.py",
    ]
    file_names = [
        arg.rsplit("->")[-1].split(":")[-1] for arg in file_name_args
    ]

    for options in (tuple(itertools.chain(*v)) for v in itertools.product(
        [(), ("--stream-split-threshold=0",)],

        #[("--some-specific-test",)],
    )):
        print("testing: " + " ".join(options))
        # Create
        cmd = ["./create.py"]
        cmd.extend(options)
        cmd.extend(file_name_args)
        with tempfile.NamedTemporaryFile() as f:
            archive_path = f.name
            cmd.extend(["--output", archive_path])
            subprocess.run(cmd, check=True)

            # List index
            cmd = ["./read.py", archive_path]
            #subprocess.run(cmd, check=True)
            lines = subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout.decode("utf8").splitlines()
            assert lines == file_names

            # Extract streaming
            with tempfile.TemporaryDirectory() as d:
                cmd = ["./read.py", archive_path, "--extract", d]
                subprocess.run(cmd, check=True)
                assert_dir(d, file_name_args, file_names)

            # Extract random access
            with tempfile.TemporaryDirectory() as d:
                # Extract each item in individual calls.
                for name in reversed(file_names):
                    cmd = ["./read.py", archive_path, "--extract", d, name]
                    subprocess.run(cmd, check=True)
                assert_dir(d, file_name_args, file_names)

def assert_dir(d, file_name_args, file_names):
    found_files = os.listdir(d)
    assert set(found_files) == set(file_names)
    for arg, name in zip(file_name_args, file_names):
        source_path = arg.split("->")[0]
        assert read_file(source_path) == read_file(os.path.join(d, name)), name

def read_file(path):
    with open(path, "rb") as f:
        return f.read()

if __name__ == "__main__":
    main()
