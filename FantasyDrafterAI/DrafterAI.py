import pandas as pd
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_logging(log_path: str = 'draft_log.txt') -> None:
    """Attach console and file handlers.

    Called from __main__ rather than at import time so that importing this
    module (e.g. from build_rankings.py) never truncates an existing draft log.
    """
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    file_handler = logging.FileHandler(log_path, mode='w')
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


class TheGeneralManager:
    RANKINGS_DIR = Path(__file__).parent / "2026_Rankings"
    TEAM_SIZE = 12
    NUM_ROUNDS = 15
    DRAFT_POSITION = 6
    POSITION_LIMITS = {'WR': 5, 'RB': 4, 'QB': 2, 'TE': 2, 'K': 1, 'DST': 1}

    # Keepers are optional. Leave False to run an open draft; set True once
    # initialize_keeper_assignments() holds this season's picks.
    USE_KEEPERS = False

    # Guaranteed by build_rankings.py; every ranking file carries all of them
    REQUIRED_COLUMNS = ('PLAYER NAME', 'POS', 'POS RANK', 'TEAM', 'BYE WEEK',
                        'ADP', 'ADP ROUND', 'HIGH', 'LOW', 'STDEV')

    def __init__(self) -> None:
        self.keeper_assignments = self.initialize_keeper_assignments() if self.USE_KEEPERS else {}
        self.keepers = self.extract_keeper_players()

        self.overall_df = self.load_data("OVR_Rankings.csv")
        self.position_dfs = {pos: self.load_data(f"{pos}_Rankings.csv")
                             for pos in self.POSITION_LIMITS}

        self.validate_keepers()
        self.initialize_draft()

    def load_data(self, file_name: str) -> pd.DataFrame:
        """Load a ranking CSV, ordered by ADP.

        Files come from build_rankings.py and already carry POS and BYE WEEK,
        so no cross-file enrichment is needed.
        """
        path = self.RANKINGS_DIR / file_name
        try:
            df = pd.read_csv(path)
        except (FileNotFoundError, pd.errors.EmptyDataError, pd.errors.ParserError) as e:
            logger.error(f"Error loading {path}: {e}")
            raise

        missing = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(
                f"{file_name} is missing required column(s): {missing}. "
                f"Re-run build_rankings.py to regenerate {self.RANKINGS_DIR.name}."
            )

        df['POS'] = df['POS'].str.upper().str.replace(r'\d+', '', regex=True)
        return df

    def validate_keepers(self) -> None:
        """Fail loudly if a keeper is absent from this year's rankings.

        No keepers is a valid setup - the draft simply runs open. When they are
        configured, names must match the rankings exactly; sources differ on
        suffixes, so 'Patrick Mahomes II' will not match FFC's 'Patrick Mahomes'.
        """
        if not self.keepers:
            logger.info("No keepers configured - running an open draft.")
            return

        known = set(self.overall_df['PLAYER NAME'])
        missing = [player for player in self.keepers if player not in known]
        if missing:
            raise ValueError(
                f"Keeper(s) not found in {self.RANKINGS_DIR.name}: {missing}. "
                "Update initialize_keeper_assignments() with this year's keepers, "
                "spelled as they appear in OVR_Rankings.csv."
            )

    def initialize_keeper_assignments(self) -> dict:
        """Keepers by round, as {round: [{team_index: player_name}, ...]}.

        Only read when USE_KEEPERS is True. Team indexes are 0-based, so team
        index 4 is Team_5. Return {} for no keepers.

        STALE: these are the 2024 assignments, kept as a format reference.
        Replace with this season's before setting USE_KEEPERS = True.
        """
        return {
            1: [{2: "Tyreek Hill"}, {4: "CeeDee Lamb"}, {6: "Amon-Ra St. Brown"}, {7: "Ja'Marr Chase"}, {8: "Christian McCaffrey"}],
            2: [{0: "Nico Collins"}, {1: "Saquon Barkley"}, {9: "Kyren Williams"}],
            3: [{3: "Patrick Mahomes II"}, {self.DRAFT_POSITION - 1: "Isiah Pacheco"}],
            5: [{10: "Stefon Diggs"}, {11: "Michael Pittman Jr."}],
        }

    def extract_keeper_players(self) -> list:
        """Extract all keeper players from the keeper assignments."""
        return [player for round_keeper in self.keeper_assignments.values()
                for team_keeper in round_keeper
                for player in team_keeper.values()]

    def initialize_draft(self) -> None:
        """Initialize draft state."""
        self.available_players = self.overall_df[~self.overall_df['PLAYER NAME'].isin(self.keepers)].copy()
        self.drafted_players = {f'Team_{i+1}': [] for i in range(self.TEAM_SIZE)}
        self.team_positions = {f'Team_{i+1}': {pos: 0 for pos in self.POSITION_LIMITS} for i in range(self.TEAM_SIZE)}
        self.team_bye_weeks = {f'Team_{i+1}': [] for i in range(self.TEAM_SIZE)}

    def pick_player(self, team: int, round_num: int) -> str:
        """Simulate picking a player for a team, considering keepers."""
        team_name = f'Team_{team + 1}'
        keeper = self.get_keeper_for_team(team, round_num + 1)
        if keeper:
            logger.info(f"Keeper: {keeper} is automatically assigned to {team_name} in Round {round_num + 1}")
            self.update_team_positions(team_name, keeper)
            return keeper

        if self.available_players.empty:
            logger.info("No more players available!")
            return None

        pick = self.select_best_available_player(team_name)
        if pick:
            self.update_dataframes_with_pick(pick)
            self.update_team_positions(team_name, pick)
        return pick

    def update_dataframes_with_pick(self, player_name: str) -> None:
        """Update all relevant dataframes by removing the picked player."""
        self.available_players = self.available_players[self.available_players['PLAYER NAME'] != player_name]
        for pos, df in self.position_dfs.items():
            df.drop(df[df['PLAYER NAME'] == player_name].index, inplace=True)

    def filter_by_position_limits(self, team_name: str) -> pd.DataFrame:
        """Available players that team_name still has an open roster slot for."""
        if self.available_players.empty:
            return self.available_players
        return self.available_players[
            self.available_players.apply(
                lambda row: self.team_positions[team_name][row['POS']] < self.POSITION_LIMITS[row['POS']], axis=1
            )
        ]

    def select_best_available_player(self, team_name: str) -> str:
        """Select the best player by ADP while respecting position limits."""
        filtered_players = self.filter_by_position_limits(team_name)
        if filtered_players.empty:
            logger.warning(f"{team_name} has no eligible players left within position limits.")
            return None
        return filtered_players.iloc[0]['PLAYER NAME']

    def get_keeper_for_team(self, team: int, round_num: int) -> str:
        """Get the keeper player for the team in the given round."""
        for keeper_info in self.keeper_assignments.get(round_num, []):
            if team in keeper_info:
                return keeper_info[team]
        return None

    def update_team_positions(self, team_name: str, player_name: str) -> None:
        """Update the team's position counts and bye weeks after picking a player."""
        player_data = self.overall_df.loc[self.overall_df['PLAYER NAME'] == player_name]
        player_pos = player_data['POS'].values[0]
        bye_week = player_data['BYE WEEK'].values[0]

        self.team_positions[team_name][player_pos] += 1
        self.team_bye_weeks[team_name].append(bye_week)
        logger.info(f"{team_name} now has {self.team_positions[team_name][player_pos]} {player_pos}(s) after picking {player_name} (Bye Week: {bye_week}).")

    def simulate_draft(self, real_time: bool = False, user_input_for_all: bool = False) -> None:
        """Perform a mock draft given the league's current settings, with optional real-time input."""
        self.remove_keepers_from_available_players()
        if real_time:
            self.perform_real_time_draft(user_input_for_all=user_input_for_all)
        else:
            self.perform_standard_draft()

    def remove_keepers_from_available_players(self) -> None:
        """Remove keeper players from the available players list."""
        self.available_players = self.available_players[~self.available_players['PLAYER NAME'].isin(self.keepers)]

    def perform_standard_draft(self, start_round: int = 0, start_pick: int = 0) -> None:
        """Perform the draft starting from a specific round and pick."""
        draft_order = self.get_draft_order()
        for round_num in range(start_round, self.NUM_ROUNDS):
            for pick_num in range(start_pick, len(draft_order[round_num])):
                team = draft_order[round_num][pick_num]
                pick = self.pick_player(team, round_num)
                if pick:
                    self.drafted_players[f'Team_{team + 1}'].append(pick)
                    logger.info(f"Round: {round_num + 1} | Team_{team + 1} picks {pick}")
            start_pick = 0  # Reset start_pick after the first round
        self.save_draft_results()

    def perform_real_time_draft(self, user_input_for_all: bool = False) -> None:
        """Manage real-time draft, delegating to user picks or simulated picks."""
        draft_order = self.get_draft_order()

        for round_num in range(self.NUM_ROUNDS):
            for pick_num, team in enumerate(draft_order[round_num]):
                if user_input_for_all or team + 1 == self.DRAFT_POSITION:
                    if self.handle_user_pick(round_num, pick_num, team):
                        return  # Auto-complete triggered, exit real-time loop
                else:
                    self.handle_pick(round_num, pick_num, team)

    def handle_user_pick(self, round_num: int, pick_num: int, team: int) -> bool:
        """Handles user input for picks."""
        team_name = f'Team_{team + 1}'
        if self.assign_keeper_if_available(team_name, round_num, team):
            return False

        logger.info(f"Round {round_num + 1} | {team_name}'s Turn{' (Your Team)' if team + 1 == self.DRAFT_POSITION else ''}")

        while True:
            user_input = input("Enter 'top [n]' to see top n players, 'team' to view your players, '.' to auto-draft pick, 'draft' to auto-complete draft, or player name: ").strip().lower()

            if user_input.startswith('top'):
                try:
                    top_n = int(user_input.split()[1])
                    self.show_best_available_players(top_n=top_n)
                except (IndexError, ValueError):
                    print("Invalid input for 'top'. Please use the format 'top [n]', where n is the number of players to display.")
            elif user_input == 'team':
                self.show_team_players()
            elif user_input == '.':
                return self.auto_draft_pick(round_num, team)
            elif user_input == 'draft':
                return self.auto_complete_draft(round_num, pick_num, team)
            else:
                if self.handle_player_selection(team_name, user_input, round_num):
                    return False
                else:
                    print(f"'{user_input}' is not a valid player name. Please try again.")

    def show_team_players(self) -> None:
        """Display the current selected players, their bye weeks, and remaining position limits for the user's team."""
        team_name = f'Team_{self.DRAFT_POSITION}'
        team_players = self.drafted_players[team_name]
        team_positions = self.team_positions[team_name]
        team_bye_weeks = self.team_bye_weeks[team_name]

        print(f"\n{team_name}'s Current Roster:")
        if team_players:
            for player, bye_week in zip(team_players, team_bye_weeks):
                player_pos = self.overall_df.loc[self.overall_df['PLAYER NAME'] == player, 'POS'].values[0]
                print(f"{player} ({player_pos}, Bye Week: {bye_week})")
        else:
            print("No players drafted yet.")

        print(f"\n{team_name}'s Position Limits:")
        for pos, limit in self.POSITION_LIMITS.items():
            current_count = team_positions[pos]
            remaining = limit - current_count
            print(f"{pos}: {current_count}/{limit} (Remaining: {remaining})")

    def assign_keeper_if_available(self, team_name: str, round_num: int, team: int) -> bool:
        """Assign keeper if available for the current team and round."""
        keeper = self.get_keeper_for_team(team, round_num + 1)
        if keeper:
            logger.info(f"Keeper: {keeper} is automatically assigned to {team_name} in Round {round_num + 1}")
            self.drafted_players[team_name].append(keeper)
            self.update_team_positions(team_name, keeper)
            self.update_dataframes_with_pick(keeper)
            return True
        return False

    def auto_draft_pick(self, round_num: int, team: int) -> bool:
        """Auto draft the next best available player."""
        return self.handle_pick(round_num, None, team)

    def auto_complete_draft(self, round_num: int, pick_num: int, team: int) -> bool:
        """Auto-complete the rest of the draft starting from the current round and pick."""
        # Auto-draft the current pick
        self.handle_pick(round_num, pick_num, team)
        # Continue the draft from the next pick
        self.perform_standard_draft(start_round=round_num, start_pick=pick_num + 1)
        return True  # Indicate that the draft is completed

    def handle_pick(self, round_num: int, pick_num: int, team: int) -> bool:
        """Handles a single draft pick, either simulated or user-driven."""
        team_name = f'Team_{team + 1}'
        pick = self.pick_player(team, round_num)
        if pick:
            self.drafted_players[team_name].append(pick)
            logger.info(f"Round: {round_num + 1} | {team_name} picks {pick}")
        return False

    def handle_player_selection(self, team_name: str, user_input: str, round_num: int) -> bool:
        """Handle the selection of a player based on user input."""
        matching_players = self.available_players[self.available_players['PLAYER NAME'].str.lower() == user_input]
        if not matching_players.empty:
            pick = matching_players.iloc[0]['PLAYER NAME']
            self.update_dataframes_with_pick(pick)
            self.update_team_positions(team_name, pick)
            self.drafted_players[team_name].append(pick)
            logger.info(f"Round: {round_num + 1} | {team_name} picks {pick}")
            return True
        else:
            logger.warning(f"Invalid input: {user_input}. Please try again.")
            return False

    def show_best_available_players(self, top_n: int = 12) -> None:
        """Show the best available players by ADP, filtered by remaining position limits."""
        filtered_players = self.filter_by_position_limits(f'Team_{self.DRAFT_POSITION}')

        if filtered_players.empty:
            print("\nNo players available that fit your remaining position limits.")
            return

        print(f"\nTop {top_n} Best Available Players:")
        for _, player in filtered_players.head(top_n).iterrows():
            pos_label = f"{player['POS']}{player['POS RANK']}"
            print(
                f"{player['PLAYER NAME']:<26} {pos_label:<6} {player['TEAM']:<4} "
                f"Bye {str(player['BYE WEEK']):<3} ADP {player['ADP']:<6} "
                f"(Rd {player['ADP ROUND']}, drafted {player['HIGH']}-{player['LOW']}, sd {player['STDEV']})"
            )

    def save_draft_results(self) -> None:
        """Save the draft results to a CSV file."""
        logger.info("\n\nNGFL Mock Draft:")
        logger.info("Draft simulation completed. Full Draft Results @ draft_results.csv")

        max_picks = max(len(picks) for picks in self.drafted_players.values())
        draft_results_df = pd.DataFrame(
            {team: picks + [None] * (max_picks - len(picks)) for team, picks in self.drafted_players.items()}
        ).transpose()
        draft_results_df.columns = [f'Pick_{i+1}' for i in range(max_picks)]
        draft_results_df.index.name = 'Team'
        draft_results_df.reset_index(inplace=True)
        draft_results_df.to_csv('draft_results.csv', index=False)

    def get_draft_order(self) -> list:
        """Generate a snake draft order."""
        return [list(range(self.TEAM_SIZE)) if round_num % 2 == 0 else list(range(self.TEAM_SIZE-1, -1, -1))
                for round_num in range(self.NUM_ROUNDS)]

if __name__ == "__main__":
    setup_logging()
    real_time = input("Would you like to run in real-time mode? (yes/no): ").strip().lower() == 'yes'
    if real_time:
        user_input_for_all = input("Would you like to input picks for all teams? (yes/no): ").strip().lower() == 'yes'
        MyGM = TheGeneralManager()
        MyGM.simulate_draft(real_time=True, user_input_for_all=user_input_for_all)
    else:
        MyGM = TheGeneralManager()
        MyGM.simulate_draft(real_time=False)
