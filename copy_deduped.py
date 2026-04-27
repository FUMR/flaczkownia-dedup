#!/usr/bin/env python3

import argparse
import os
import shutil
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrates symlinks view to copied view")
    # parser.add_argument("raw_directory", type=Path, help="Path to the directory containing raw flaczkownia")
    parser.add_argument("deduped_directory", type=Path, help="Path to the directory containing dedup symlinks")
    parser.add_argument("output_directory", type=Path, help="Path to the directory where we copy deduped files")
    args = parser.parse_args()

    # raw_dir: Path = args.raw_directory
    deduped_dir: Path = args.deduped_directory
    output_dir: Path = args.output_directory

    # if not raw_dir.is_dir():
    #     print(f"Error: '{raw_dir}' is not a valid directory.")
    #     exit(1)

    if not deduped_dir.is_dir():
        print(f"Error: '{deduped_dir}' is not a valid directory.")
        exit(2)

    if not output_dir.is_dir():
        print(f"Error: '{output_dir}' is not a valid directory.")
        exit(2)

    msgs = {}

    for fname in os.listdir(deduped_dir):
        msg_id = int(fname.split(" ", 1)[0])
        msgs[msg_id] = fname

    def files(msg_id):
        fname = (deduped_dir / msgs[msg_id])
        if fname.is_dir():
            for root, dirs, files in fname.walk():
                for file in files:
                    yield (root / file).relative_to(deduped_dir)
        else:
            yield fname.relative_to(deduped_dir)

    for msg_id in sorted(msgs.keys(), reverse=True):
        print(f"Processing message {msg_id}")
        for f in files(msg_id):
            print("  ", f)
            print(f"  Copying: {deduped_dir / f} -> {output_dir / f}")
            (output_dir / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(deduped_dir / f, output_dir / f)
        # print(f"  Removing: {raw_dir / msgs[msg_id]}")
        # os.remove(raw_dir / msgs[msg_id])
