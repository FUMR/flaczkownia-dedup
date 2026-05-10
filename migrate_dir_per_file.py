#!/usr/bin/env python3

import argparse
import logging
import os
import shutil
from pathlib import Path


def migrate_dir_per_file(view_dir: str, dir_per_file_prefixes: frozenset[str]):
    logger.info(f"Starting migration with prefixes: {dir_per_file_prefixes}")

    for prefix in dir_per_file_prefixes:
        prefix_path = Path(view_dir) / prefix
        if not prefix_path.is_dir():
            logger.warning(f"Prefix path {prefix_path} is not a directory, skipping")
            continue

        logger.info(f"Processing prefix: {prefix_path}")

        for entry in sorted(prefix_path.iterdir()):
            if entry.is_file():
                new_dir = prefix_path / entry.name
                new_file = new_dir / entry.name

                if new_file.exists():
                    logger.info(f"Already migrated: {new_file}")
                    continue

                tmp_dir = new_dir.with_suffix(entry.suffix + ".tmpdir")
                tmp_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(entry), str(tmp_dir / entry.name))
                tmp_dir.rename(new_dir)
                logger.info(f"Migrated: {entry} -> {new_file}")

    for root, dirs, files in os.walk(view_dir, topdown=False):
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass

    logger.info("Migration finished")


if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=os.environ.get("LOG_LEVEL", "INFO").upper())
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Migrate deduped view to per-file directory structure")
    parser.add_argument("--view-dir", required=True, help="Deduped view directory")
    parser.add_argument("--dir-per-file-path", action="append", required=True,
                        help="Path prefixes where loose files should be wrapped (repeatable)")
    args = parser.parse_args()

    migrate_dir_per_file(args.view_dir, frozenset(args.dir_per_file_path))
