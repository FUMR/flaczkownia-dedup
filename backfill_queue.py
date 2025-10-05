#!/usr/bin/env python3

import argparse
import os

import httpx


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfills the dedup queue with existing tgmount files")
    parser.add_argument("directory", help="Path to the directory containing files")
    parser.add_argument("url", help="URL to send POST requests to")
    parser.add_argument("--min-msgid", type=int, default=0, help="Message ID to start with")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a valid directory.")
        exit(1)

    files = {}

    for fname in os.listdir(args.directory):
        msg_id = int(fname.split(" ", 1)[0])
        if msg_id > args.min_msgid:
            files[msg_id] = fname

    with httpx.Client() as httpx_client:
        for msg_id in sorted(files.keys(), reverse=True):
            fname = files[msg_id]
            print(f"Processing message {msg_id} (filename {fname})")
            response = httpx_client.post(args.url, json={"fname": fname})
            print(response.text)
