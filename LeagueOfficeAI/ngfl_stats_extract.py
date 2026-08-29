import requests
import pandas as pd

# ====== CONFIG ======
LEAGUE_ID = "1261437958930563072"  # <-- your league ID
SAVE_CSV = True
CSV_NAME = "LeagueOfficeAI/quarterly_manager_data.csv"

# Optional week filters
START_WEEK = 9  # e.g. 1
END_WEEK = 14    # e.g. 4


# ----------------- API HELPERS -----------------
def get_league(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}"
    resp = requests.get(url)
    resp.raise_for_status()
    
    return resp.json()


def get_league_users(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/users"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()


def get_league_rosters(league_id):
    url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()


def get_matchups_for_week(league_id, week):
    url = f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()


# ----------------- BUILD MAPS -----------------
def build_user_map(users):
    user_map = {}
    for u in users:
        display_name = u.get("display_name", "")
        team_name = u.get("metadata", {}).get("team_name", "") if u.get("metadata") else ""
        user_map[u["user_id"]] = {
            "display_name": display_name,
            "team_name": team_name or display_name
        }
    return user_map


def build_roster_owner_map(rosters, user_map):
    roster_map = {}
    for r in rosters:
        owner_id = r.get("owner_id")
        owner_info = user_map.get(owner_id, {"display_name": "Unknown", "team_name": "Unknown"})
        roster_map[r["roster_id"]] = {
            "owner_id": owner_id,
            "owner_display_name": owner_info["display_name"],
            "team_name": owner_info["team_name"]
        }
    return roster_map


# ----------------- WEEK RANGE -----------------
def determine_weeks_to_pull(league, start_week=None, end_week=None):
    settings = league.get("settings", {}) if league else {}
    playoff_week_start = settings.get("playoff_week_start")

    if playoff_week_start:
        max_week = playoff_week_start - 1
    else:
        max_week = 18  # fallback

    if start_week is None and end_week is None:
        return list(range(1, max_week + 1))

    if start_week is None and end_week is not None:
        start_week = 1

    if start_week is not None and end_week is None:
        end_week = max_week

    start_week = max(1, start_week)
    end_week = min(max_week, end_week)

    return list(range(start_week, end_week + 1))


# ----------------- NUMBER → WORD -----------------
def number_to_word(n: int) -> str:
    """
    Convert 1 -> 'one', 2 -> 'two', ... up to 20.
    Good enough for fantasy weeks.
    """
    words = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
        11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
        15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
        19: "nineteen", 20: "twenty"
    }
    return words.get(n, str(n))


def main(league_id, start_week=None, end_week=None):
    league = get_league(league_id)
    users = get_league_users(league_id)
    rosters = get_league_rosters(league_id)

    user_map = build_user_map(users)
    roster_map = build_roster_owner_map(rosters, user_map)

    weeks = determine_weeks_to_pull(league, start_week, end_week)

    # ========== STEP 1: GET LONG/WIDE-READY DATA ==========
    long_rows = []

    for wk in weeks:
        matchups = get_matchups_for_week(league_id, wk)

        # group by matchup_id so we can find opponents
        matchup_groups = {}
        for m in matchups:
            mid = m.get("matchup_id")
            if mid is None:
                mid = f"no_mid_{m.get('roster_id')}"
            matchup_groups.setdefault(mid, []).append(m)

        for matchup_id, entries in matchup_groups.items():
            for entry in entries:
                roster_id = entry.get("roster_id")
                points = entry.get("points", 0)

                # opponent
                opponent_points = None
                if len(entries) > 1:
                    for e in entries:
                        if e is not entry:
                            opponent_points = e.get("points", 0)
                            break

                owner_info = roster_map.get(roster_id, {
                    "owner_display_name": "Unknown",
                    "team_name": "Unknown"
                })

                # result for this week
                result = None
                if opponent_points is not None:
                    if points > opponent_points:
                        result = "W"
                    elif points < opponent_points:
                        result = "L"
                    else:
                        result = "T"

                long_rows.append({
                    "week": wk,
                    "manager": owner_info["owner_display_name"],
                    "team_name": owner_info["team_name"],
                    "points": points,
                    "result": result
                })

    long_df = pd.DataFrame(long_rows)

    # ========== STEP 2: PIVOT TO YOUR FORMAT ==========
    # We'll build it manager by manager
    managers = long_df["manager"].unique()
    wide_records = []

    for idx, manager in enumerate(sorted(managers), start=1):
        mgr_df = long_df[long_df["manager"] == manager]

        record = {
            "id": idx,
            "manager": manager,
        }

        # add week columns
        for wk in weeks:
            wk_word = number_to_word(wk)
            col_name = f"week_{wk_word}"
            # get points for this week
            this_week = mgr_df[mgr_df["week"] == wk]
            if not this_week.empty:
                record[col_name] = float(this_week.iloc[0]["points"])
            else:
                record[col_name] = None  # or 0 if you prefer

        # wins/losses/ties
        wins = (mgr_df["result"] == "W").sum()
        losses = (mgr_df["result"] == "L").sum()
        ties = (mgr_df["result"] == "T").sum()

        record["wins"] = wins
        record["losses"] = losses
        # your sample called this "score" but it was 0 everywhere, so I'll call it ties
        # change the key name below if you want exactly "score"
        record["score"] = ties

        wide_records.append(record)

    wide_df = pd.DataFrame(wide_records)

    # order columns: id, manager, week_..., wins, losses, score
    week_cols = []
    for wk in weeks:
        wk_word = number_to_word(wk)
        week_cols.append(f"week_{wk_word}")

    col_order = ["id", "manager"] + week_cols + ["wins", "losses", "score"]
    wide_df = wide_df[col_order]

    print(wide_df)

    if SAVE_CSV:
        wide_df.to_csv(CSV_NAME, index=False)
        print(f"Saved to {CSV_NAME}")


if __name__ == "__main__":
    main(LEAGUE_ID, start_week=START_WEEK, end_week=END_WEEK)
