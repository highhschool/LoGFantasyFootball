
TO RUN:
parent MUST be NGFL_FantasyFootball directory.

modify -
To target specific weeks, open ngfl_stats_extract.py
change the START_WEEK and END_WEEK to the weeks you want to extract the range.

run -
>> python .\LeagueOfficeAI\ngfl_stats_extract.py
output - 
>> ... (table) ...
>> Saved to LeagueOfficeAI/quarterly_manager_data.csv

run - 
>> python .\LeagueOfficeAI\smart_awards.py
output - 
>> - INFO -  -- STARTING -- 
>> - INFO - reading csv file...
>> - INFO - Building D:\LOGFantasyFootball\LeagueOfficeAI\quarterly_manager_tiers.csv...
>> - INFO -  -- FINISHED --

File should now be created, quarterly_manager_tiers.csv
Rename the file to not override it.
=====================================================================
FantasyDrafterAI
=====================================================================
parent MUST be the FantasyDrafterAI directory.

Rankings are pulled from Fantasy Football Calculator's public ADP API
(free, no API key). They are NOT committed - regenerate them each year.

modify -
To change season or league format, open build_rankings.py
change YEAR, TEAMS, or SCORING (ppr | half-ppr | standard).

run -
>> python .\build_rankings.py
output -
>> - INFO - got 267 players from 7986 drafts (2026-08-20 to 2026-08-27)
>> - INFO - wrote OVR_Rankings.csv (267 players)
>> - INFO - wrote QB_Rankings.csv (30 players)
>> ...
>> - INFO - rankings ready in ...\FantasyDrafterAI\2026_Rankings

Creates 2026_Rankings/ with OVR + one file per position, ordered by ADP.
Point DrafterAI.py at it by setting RANKINGS_DIR. Prior years are kept
alongside (2025_Rankings/) as archives.

KEEPERS ARE OPTIONAL. By default USE_KEEPERS = False and the drafter
runs an open draft with no keepers at all.

To use them, fill in initialize_keeper_assignments() in DrafterAI.py and
set USE_KEEPERS = True. Keepers are keyed by round, then by 0-based team
index, so {1: [{4: "Ja'Marr Chase"}]} keeps Chase for Team_5 in round 1.
Names must match OVR_Rankings.csv exactly - the drafter refuses to start
if a configured keeper isn't in the rankings. Note that name suffixes
differ between sources ("Patrick Mahomes", not "Patrick Mahomes II").

run -
>> python .\DrafterAI.py
>> Would you like to run in real-time mode? (yes/no):

  no  - simulates all 15 rounds, writes draft_results.csv
  yes - prompts on your pick (DRAFT_POSITION). Commands:
          top [n]  show n best available w/ ADP, bye, draft range
          team     show your roster and remaining position limits
          .        auto-pick the best available
          draft    auto-complete the rest of the draft

Full pick log lands in draft_log.txt (overwritten each run).
