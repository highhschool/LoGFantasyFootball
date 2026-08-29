# The League of Goons 2023 Quarterly Award Algo

import csv
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# CONSTANTS
QUARTERLY_MANAGER_DATA = Path(__file__).parent / "quarterly_manager_data.csv"
QUARTERLY_MANAGER_TIERS = Path(__file__).parent / "quarterly_manager_tiers.csv"


class ManagerTierList:
    """ Reads the current manager data list for the quarter (4 weeks).
        Creates new CSV file with sorted Manager Tier List.
    """

    def __init__(self) -> None:
        # will be filled after reading csv
        self.manager_file: list[dict] = []
        self.week_fields: list[str] = []  # e.g. ["week_one", "week_two", "week_three", "week_four"]

    def manager_setup(self) -> list:
        """Read the CSV and detect which week_* columns are present."""
        manager_list = []
        logging.info("reading csv file...")
        try:
            with open(QUARTERLY_MANAGER_DATA, mode='r') as csv_file:
                csv_reader = csv.DictReader(csv_file)
                # detect week columns from header
                fieldnames = csv_reader.fieldnames or []
                self.week_fields = [f for f in fieldnames if f.startswith("week_")]
                # keep order as in file
                for row in csv_reader:
                    manager_list.append(row)
        except Exception as e:
            logging.warning(f"EXCEPTION HIT: {e}")
        return manager_list

    def is_standout_player(self, my_manager: dict, week: str) -> bool:
        """
        A manager is a standout for a given week if:
        - that week column exists
        - they have a real score (>0)
        - no other manager has a higher score for that same week
        """
        if not self.manager_file:
            return False

        my_val = float(my_manager.get(week, 0) or 0)
        if my_val <= 0:
            return False

        for other in self.manager_file:
            other_val = float(other.get(week, 0) or 0)
            if other_val > my_val:
                return False

        logging.debug(f"standout manager: {my_manager.get('manager', 'UNKNOWN')} for {week}")
        return True

    def calculate_manager_grade(self, manager: dict) -> dict:
        """
        Scoring logic:
        1. Base Score = sum of present week_* cols
        2. Boost: +100 if week >= 100, -100 if 0 < week <= 65
        3. Wins/losses: +25 per win, -25 per loss
        4. Standout: +20% of that week's score if they led the league that week
        """
        base_scoring_count = 0.0
        boost_scoring_count = 0.0
        win_loss_scoring_count = 0.0
        standout_manager_count = 0.0
        standout_manager_tally = 0

        manager_name = str(manager.get("manager", "UNKNOWN"))
        manager_wins = int(manager.get("wins", 0))
        manager_loses = int(manager.get("losses", 0))

        # loop over only the weeks actually present in the CSV
        for week_field in self.week_fields:
            week_val = float(manager.get(week_field, 0) or 0)

            # 1) base
            base_scoring_count += week_val

            # 2) boost
            if week_val >= 100:
                boost_scoring_count += 100
            elif 0 < week_val <= 65:
                # don't punish missing weeks (0), only real low weeks
                boost_scoring_count -= 100

            # 4) standout
            if week_val > 0 and self.is_standout_player(manager, week_field):
                standout_manager_count += week_val * 0.20
                standout_manager_tally += 1

        # 3) wins / losses
        win_loss_scoring_count += (manager_wins * 25)
        win_loss_scoring_count -= (manager_loses * 25)

        updated_manager_score = (
            base_scoring_count
            + boost_scoring_count
            + win_loss_scoring_count
            + standout_manager_count
        )

        return {
            "manager": manager_name,
            "score": round(updated_manager_score, 2),
            "base_scoring": round(base_scoring_count, 2),
            "boost_scoring": boost_scoring_count,
            "win_loss_scoring": win_loss_scoring_count,
            "standout_scoring": round(standout_manager_count, 2),
            "standout_tally": standout_manager_tally,
        }

    def build_csv_file(self, file_headers: dict, csv_file_name: str, sorted_manager_list: list) -> None:
        logging.info(f"Building {csv_file_name}...")
        with open(csv_file_name, "w", newline='') as csv_file:
            csv_writer = csv.DictWriter(csv_file, delimiter=",", fieldnames=file_headers)
            csv_writer.writeheader()
            for data in sorted_manager_list:
                csv_writer.writerow(data)

    def smart_runner(self) -> None:
        logging.info(" -- STARTING -- ")
        # load managers & detect weeks
        self.manager_file = self.manager_setup()

        calculated_manager_list = []
        for manager in self.manager_file:
            calculated_manager_data = self.calculate_manager_grade(manager)
            calculated_manager_list.append(calculated_manager_data)

        # sort best -> worst
        sorted_list = sorted(calculated_manager_list, key=lambda x: x["score"], reverse=True)

        # build csv
        score_file_header = sorted_list[0].keys()
        self.build_csv_file(score_file_header, QUARTERLY_MANAGER_TIERS, sorted_list)

        logging.info(" -- FINISHED -- ")


if __name__ == "__main__":
    MyTierList = ManagerTierList()
    MyTierList.smart_runner()
