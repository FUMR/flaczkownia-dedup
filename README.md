# Flaczkownia Dedup

## Story

On flaczkownia we have looots of downloaded tracks, more than half are downloaded multiple times.
We need a way to not import those to self-hosted streaming services mutliple times as this makes library literally unusable.


## Analysis of the problem

After time-consuming analysis of the problem @JuniorJPDJ and @lobsonwf came up with basic assumptions:
- We SHOULD NOT have duplicated tracks in the same album (doesn't matter if those came from the same or multiple sources)
- Tidal and Deezer downloaded tracks CAN create separate albums if metadata differs (preferably no, but we can live with that)
- Sometimes - when track is first released as a single, then album containing the track is released - we should not deduplicate that - those are separate releases
- We don't want to remove older tracks to supersede those with new ones after those are imported already - this can create problems with disappearing tracks with metadata created by external software, like:
  - favourites
  - ratings
  - comments
  - share links
- We don't care too much about directory structure - external software will anyway store database with parsed files after import
- We need to pass new files import to dedup and allow checking of duplicates in a real time
- Backfill can be external script, no need for backfill functionality in main daemon
- Backfill should prefer newer files, live dedup should prefer older files - we assume backfill is not imported to external software yet so no additional metadata exist yet


## The solution

We somehow need to understand which files are similar enough (acoustic-wise). Acoustic hashing algorithms are great solution for that problem.
That's not enough tho as we should not remove singles or album released tracks that were released before as singles - that would make albums incomplete.

What we came up with is storing unique tuple of album name, album track number and acoustic hash of the track.
That would make sure that we deduplicate only inside the album and we don't replace miss-placed single albums from albums with the same name as the single.

If there's no existing track with that tuple, that would mean the track is not duplicate and we can import it safely.

AcoustID / Chromaprint was ideal first choice for acoustic hash as it's popular and seems to work great for finding track metadata based on acoustic characteristics. What we found after trying generating those for album downloaded from Tidal and Deezer was that those hashes were DIFFERENT. That means it doesn't suit our needs. We asked several AI agents to suggest us more similar solutions. We came up with LastFM fingerprinting library, which we found not working with Python 3 (LOL).

Next one we found was audioprint. We tested it and it was working PERFECTLY. After some shit-talk about hash collisions (those hashes aren't too big) we decided to use it as we don't care too much about collisions - we only compare the tuples, chances that album contains a collision is minimal and we for sure prefer that than having different hashes for the same track. Unfortunetaly it's not on pypi nor does contain setup.py or pyproject.toml, we decided to fork it and prepare PR with pyproject file. We use fork in requirements.txt but it would be great to move to official repository someday.