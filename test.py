#!/usr/bin/env python3

import os
import subprocess
import tempfile

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.parse_args()

    file_names = ["create.py", "read.py", "common.py"]

    for options in [
        (),
        ("--no-index",),
        ("--no-streaming",),
    ]:
        # Create
        cmd = ["./create.py"]
        cmd.extend(options)
        cmd.extend(file_names)
        with tempfile.NamedTemporaryFile() as f:
            archive_path = f.name
            cmd.extend(["--output", archive_path])
            subprocess.run(cmd, check=True)

            # List index
            if "--no-index" not in options:
                cmd = ["./read.py", archive_path]
                lines = subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout.decode("utf8").splitlines()
                assert lines == file_names

            # Extract streaming
            if "--no-streaming" not in options:
                with tempfile.TemporaryDirectory() as d:
                    cmd = ["./read.py", archive_path, "--extract", d]
                    subprocess.run(cmd, check=True)
                    assert_dir(d, file_names)

            # Extract random access
            if "--no-index" not in options:
                with tempfile.TemporaryDirectory() as d:
                    # Extract each item in individual calls.
                    for name in reversed(file_names):
                        cmd = ["./read.py", archive_path, "--extract", d, name]
                        subprocess.run(cmd, check=True)
                    assert_dir(d, file_names)

def assert_dir(d, file_names):
    found_files = os.listdir(d)
    assert set(found_files) == set(file_names)
    for name in file_names:
        assert read_file(name) == read_file(os.path.join(d, name)), name

def read_file(path):
    with open(path, "rb") as f:
        return f.read()

if __name__ == "__main__":
    main()
