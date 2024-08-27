# The League of Goons 2023 Quarterly Award Algo

import csv
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class ManagerTierList:
    """ Reads the current 4 week manager data list.
    Creates new CSV file with sorted Manager Tier List.

    Returns:
        class object: Returns the object of this class.
    """
    manager_name = ""
    manager_file = manager_pool = manager_rankings = []
    manager_id = week_one = week_two = week_three = week_four = manager_grade = 0
    
    def __init__(self) -> None:
        pass
    
    def manager_setup(self) -> list:
        """ setup the manager list

        Returns:
            list: list of manager dictionaries
        """
        manager_list = []
        logging.info("reading csv file...")
        try:
            with open('quarterly_manager_data.csv', mode='r') as csv_file:
                csv_reader = csv.DictReader(csv_file)
                for row in csv_reader:
                    manager_list.append(row)
        except Exception as e:
            logging.warning(f"EXCEPTION HIT: {e}")
        return manager_list
    
    def is_standout_player(self, my_manager: dict, week: str) -> bool:
        """ Decides if a manager is stand out by comparing that weeks score against the other managers scores for the week.
        If the manager has the highest score for the week, they are stand out player of the week.
        
        Args:
            my_manager (dict): manager dictionary object
            week (str): one, two, three, or four weeks

        Returns:
            bool: True or False of is_standout_player?
        """
        if not self.manager_file:
            return False
        
        manager_value = float(my_manager.get(week))
        for manager in self.manager_file:
            compare_value = float(manager.get(week))
            if compare_value > manager_value:
                return False
            
        logging.debug(f"standout manager: {my_manager['manager']}")
        return True
    
    def calculate_manager_grade(self, manager: dict) -> dict:
        """ Handles the calcuation of the managers scores
        1. Base Score equals the total number of points scored in the 4 week period.
        2. Boost Scoring is the extra points given to those that hit 100 points for a week.
            2(a). Boost Scoring can also be negative if you fail to hit 65 points.
        3. Win/Loss Scoring is calcuated by multiplying each win or loss by 25. (total additive points ranging from -100 to +100 depending on the managers 4 weeks)
            3(a). Win Scoring: each win adds 25 points to a managers score.
            3(b). Loss Scoring: each loss deducts 25 points to the managers score.

        Args:
            manager (dict): dictionary containing manager data

        Returns:
            dict: dictionary containing key: manager name and value: calculated score
        """
        
        base_scoring_count = float(0)
        boost_scoring_count = float(0)
        win_loss_scoring_count = float(0)
        standout_manager_count = float(0)
        standout_manager_tally = int(0)
        
        manager_name = str(manager["manager"])
        week_one = float(manager["week_one"])
        week_two = float(manager["week_two"])
        week_three = float(manager["week_three"])
        week_four = float(manager["week_four"])
        manager_wins = int(manager["wins"])
        manager_loses = int(manager["losses"])
        manager_score = float(manager["score"])
        
        # applying basic scoring
        base_scoring_count = week_one + week_two + week_three + week_four
        
        if week_one >= 100:
            boost_scoring_count += 100
        elif week_one <= 65:
            boost_scoring_count -= 100
        if week_two >= 100:
            boost_scoring_count += 100
        elif week_two <= 65:
            boost_scoring_count -= 100
        if week_three >= 100:
            boost_scoring_count += 100
        elif week_three <= 65:
            boost_scoring_count -= 100
        if week_four >= 100:
            boost_scoring_count += 100
        elif week_four <= 65:
            boost_scoring_count -= 100
            
        # add wins and subtract loses
        win_loss_scoring_count += (manager_wins * 25)
        win_loss_scoring_count -= (manager_loses * 25)
        
        # stand-out weeks, weeks that are 20% more than the average manager week score
        # check if a manager is the stand-out player in week one
        is_standout_player_week_one = self.is_standout_player(manager, "week_one")
        if is_standout_player_week_one:
            standout_manager_count += week_one * 0.20
            standout_manager_tally += 1
        is_standout_player_week_two = self.is_standout_player(manager, "week_two")
        if is_standout_player_week_two:
            standout_manager_count += week_two * 0.20
            standout_manager_tally += 1
        is_standout_player_week_three = self.is_standout_player(manager, "week_three")
        if is_standout_player_week_three:
            standout_manager_count += week_three * 0.20
            standout_manager_tally += 1
        is_standout_player_week_four = self.is_standout_player(manager, "week_four")
        if is_standout_player_week_four:
            standout_manager_count += week_four * 0.20
            standout_manager_tally += 1
        
        # adding everything up..
        updated_manager_score = base_scoring_count + boost_scoring_count + win_loss_scoring_count + standout_manager_count
        return_dict = {"manager": manager_name, "score": round(updated_manager_score, 2), "base_scoring": round(base_scoring_count, 2), 
                       "boost_scoring": boost_scoring_count, "win_loss_scoring": win_loss_scoring_count, "standout_scoring": round(standout_manager_count, 2), "standout_tally": standout_manager_tally}
        
        return return_dict
    
    def build_csv_file(self, file_headers: dict, csv_file_name: str, sorted_manager_list: list) -> None:
        """ Building the Manager Tier List csv file

        Args:
            file_headers (dict): header of the file
            csv_file_name (str): name & location of file
            sorted_manager_list (list): sorted list of managers and their calculated score
        """
        logging.info(f"Building {csv_file_name}...")
        with open(csv_file_name, "w", newline='') as csv_file:
            csv_writer = csv.DictWriter(csv_file, delimiter=",", fieldnames=file_headers)
            # write the header
            csv_writer.writeheader()
            # write the sorted data
            for data in sorted_manager_list:
                csv_writer.writerow(data)
        return
        
    def smart_runner(self) -> None:
        """
        handles the flow of the manager tier list generation
        """
        calculated_manager_list = []
        manager_tier_file = "quarterly_manager_tiers.csv"
        
        logging.info(" -- STARTING -- ")
        
        # disect list and build each manager's updated values
        self.manager_file = self.manager_setup()

        # calculate managers scores
        for manager in self.manager_file:
            calculated_manager_data = self.calculate_manager_grade(manager)
            calculated_manager_list.append(calculated_manager_data)
        
        # sort list, first to worst
        sorted_list = sorted(calculated_manager_list, key=lambda x: x["score"], reverse=True)
        
        # build new csv file
        score_file_header = sorted_list[0].keys()
        self.build_csv_file(score_file_header, manager_tier_file, sorted_list)
        
        logging.info(f" -- FINISHED -- ")

    
if __name__ == "__main__":
    # do something
    MyTierList = ManagerTierList()
    MyTierList.smart_runner()
    