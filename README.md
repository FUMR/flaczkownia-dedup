# Flaczkownia Dedup

## 📖 Story

At **Flaczkownia**, we’ve accumulated a massive collection of downloaded tracks — and more than half of them are duplicates.
Importing all these duplicates into our self-hosted streaming services would make the music library unusable.

We needed a way to **avoid importing the same track multiple times**, even if it comes from different sources.


## 🔍 Problem Analysis

After time-consuming analysis of the problem, @JuniorJPDJ and @loobson came up with basic assumptions:
- **No duplicated tracks on the same album** - regardless of source.
- **Tidal and Deezer** tracks can create separate albums if metadata differs (not ideal, but acceptable).
- A track first released as a single and later included in an album should not be deduplicated — those are distinct releases.
- We **must not remove older tracks** that have already been imported, even if a newer version exists. Otherwise, we risk losing metadata created by external tools, such as:
  - favourites
  - ratings
  - comments
  - share links
- Directory structure doesn’t matter — external tools will manage their own database after import.
- We need to pass new files import to dedup and allow checking of duplicates in real time
- Backfill:
  - Can be handled by a separate script - no need to include it in the main daemon
  - Should prefer newer files (since they aren’t imported yet)
  - Live dedup should prefer older files (since those are already imported and possibly have metadata)


## 💡 The solution

We somehow need to understand which files are similar enough (acoustic-wise). Acoustic hashing algorithms are a great solution for that problem.
However, this alone doesn’t solve everything - we also need to distinguish between singles and album releases to avoid breaking the album's completeness.

We decided to use a unique tuple consisting of:
> (Album Name, Album Track Number, Acoustic Hash)

This ensures that:
- Deduplication happens **within the same album only**
- Singles and album versions remain distinct, even if they share the same title
- We deduplicate only inside the album, misplaced tracks with the same album name won’t overwrite each other

If a tuple doesn’t already exist — the track is **safe to import**.

## 🧠 Acoustic hashing journey

Initially, we chose **AcoustID / Chromaprint** - a well-known and reliable acoustic hashing system. Unfortunately, when testing with tracks from Tidal and Deezer, we discovered that their hashes were different for the same audio. This made them unsuitable for our use case.

We explored other options - including LastFM’s fingerprinting library, which turned out to be incompatible with Python 3...

Finally, we found audioprint, which:
- aligns perfectly with our use case
- produces consistent hashes across different audio sources
- has minimal risk of collisions (acceptable for our tuple-based comparison)

Although **audioprint** isn’t available on PyPI and lacks packaging files (`setup.py`, `pyproject.toml`), we:
- forked the repository
- added the necessary packaging support
- use our fork in requirements.txt
- looking forward to contributing our changes to upstream in the future