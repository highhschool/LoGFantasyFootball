import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TheGeneralManager:
    """Acts as an AI GM of your Team.
    Reads in data file (csv) and analyzes the league's drafters along with what pick # you fall on.
    Dynamically keeps track of Team size, position limits, bye week information. Compares player potential.
    """

    TEAM_SIZE: int = 12  # Number of teams
    NUM_ROUNDS: int = 15  # Total rounds
    DRAFT_POSITION: int = 6  # My draft pick (1-based index)
    DRAFT_ORDER: str = "snake"  # Draft order type
    MY_KEEPER: str = "Isiah Pacheco"  # Player you are keeping

    def __init__(self) -> None:
        # Keeper assignments with the format: {round: [{team_index: player_name}, ...]}
        self.keeper_assignments = {
            1: [{2: "Tyreek Hill"}, {4: "CeeDee Lamb"}, {6: "Amon-Ra St. Brown"}, {7: "Ja'Marr Chase"}, {8: "Christian McCaffrey"}],  # Round 1, Multiple Teams
            2: [{0: "Nico Collins"}, {1: "Saquon Barkley"}, {9: "Kyren Williams"}],  # Round 2, Team 1 and Team 2 and Team 10
            3: [{3: "Patrick Mahomes II"}, {self.DRAFT_POSITION - 1: "Isiah Pacheco"}],  # Round 3 and My Team
            5: [{10: "Stefon Diggs"}, {11: "Michael Pittman Jr."}],  # Round 5, Team 11 and Team 12
        }

        # Flatten keeper list to make it easier to handle later
        self.keepers = [player for round_keeper in self.keeper_assignments.values() for team_keeper in round_keeper for player in team_keeper.values()]

        try:
            self.player_list = pd.read_csv("player_list.csv")
        except FileNotFoundError:
            logging.error("player_list.csv file not found.")
            raise
        except pd.errors.EmptyDataError:
            logging.error("player_list.csv is empty.")
            raise
        except pd.errors.ParserError:
            logging.error("Error parsing player_list.csv.")
            raise

        if 'PLAYER NAME' not in self.player_list.columns:
            logging.error("player_list.csv must contain a 'PLAYER NAME' column.")
            raise

        # Remove keepers from available players
        self.available_players = self.player_list[~self.player_list['PLAYER NAME'].isin(self.keepers)]['PLAYER NAME'].tolist()
        self.drafted_players = {f'Team_{i+1}': [] for i in range(self.TEAM_SIZE)}

    def get_draft_order(self) -> list:
        """Generate a snake draft order."""
        draft_order = []
        for round_num in range(self.NUM_ROUNDS):
            if round_num % 2 == 0:
                draft_order.append(list(range(self.TEAM_SIZE)))
            else:
                draft_order.append(list(range(self.TEAM_SIZE-1, -1, -1)))
        return draft_order

    def pick_player(self, team: int, round_num: int) -> str:
        """Simulate picking a player for a team."""
        # Check if there's a keeper assigned to this team and round
        if round_num + 1 in self.keeper_assignments:
            for keeper_info in self.keeper_assignments[round_num + 1]:
                if team in keeper_info:
                    pick = keeper_info[team]
                    logging.info(f"Keeper: {pick} is automatically assigned to Team_{team + 1} in Round {round_num + 1}")
                    return pick

        if not self.available_players:
            logging.info("No more players available!")
            return None

        # Simple strategy: pick the first available player
        pick = self.available_players.pop(0)  # Remove the player from the list

        return pick

    def simulate_draft(self) -> None:
        """Perform a mock draft given the league's current settings."""
        # Ensure all keepers are removed from the available players list at the start of the draft
        for round_keeper in self.keeper_assignments.values():
            for team_keeper in round_keeper:
                for keeper in team_keeper.values():
                    if keeper in self.available_players:
                        self.available_players.remove(keeper)

        draft_order = self.get_draft_order()
        my_team_picks = []

        for round_num, round_order in enumerate(draft_order):
            logging.info(f"Round {round_num + 1}")
            for team in round_order:
                pick = self.pick_player(team, round_num)
                if pick is not None:
                    team_name = f'Team_{team + 1}'
                    self.drafted_players[team_name].append(pick)
                    if team == self.DRAFT_POSITION - 1:  # Adjust for 0-based index
                        my_team_picks.append(pick)
                    logging.info(f"Round: {round_num + 1} | {team_name} picks {pick}")

        logging.info("\n\nLeague of Goons Mock Draft:")
        logging.info("Draft simulation completed. Full Draft Results @ draft_results.csv")
        logging.info(f"My Team: {my_team_picks}")

        # Convert draft results to a DataFrame with each team as a row
        max_picks = max(len(picks) for picks in self.drafted_players.values())
        # Create DataFrame where each team is a row and columns are picks
        draft_results_df = pd.DataFrame(
            {team: picks + [None] * (max_picks - len(picks)) for team, picks in self.drafted_players.items()}
        ).transpose()
        draft_results_df.columns = [f'Pick_{i+1}' for i in range(max_picks)]
        draft_results_df.index.name = 'Team'
        draft_results_df.reset_index(inplace=True)
        draft_results_df.to_csv('draft_results.csv', index=False)

if __name__ == "__main__":
    MyGM = TheGeneralManager()
    MyGM.simulate_draft()
