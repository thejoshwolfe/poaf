#!/usr/bin/env python3

import os
import subprocess
import tempfile
import itertools

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.parse_args()

    file_name_args = [
        "empty_test_file.txt->empty_test_file_1.txt",
        "create.py",
        "read.py",
        "empty_test_file.txt->empty_test_file_2.txt",
        "empty_test_file.txt->empty_test_file_3.txt",
        "common.py",
    ]
    file_names = [
        arg.rsplit("->")[-1] for arg in file_name_args
    ]

    for options in (tuple(itertools.chain(*v)) for v in itertools.product(
        [(), ("--no-index",), ("--no-streaming",)],
        [(), ("--stream-split-threshold=0",), ("--no-compression",)],

        #[("--no-compression",)],
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
            if "--no-index" not in options:
                cmd = ["./read.py", archive_path]
                #subprocess.run(cmd, check=True)
                lines = subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout.decode("utf8").splitlines()
                assert lines == file_names

            # Extract streaming
            if "--no-streaming" not in options:
                with tempfile.TemporaryDirectory() as d:
                    cmd = ["./read.py", archive_path, "--extract", d]
                    subprocess.run(cmd, check=True)
                    assert_dir(d, file_name_args, file_names)

            # Extract random access
            if "--no-index" not in options:
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
