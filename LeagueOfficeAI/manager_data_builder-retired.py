import csv

# List of manager names
managers = [
    "Elle", "Jared", "Brayden", "Carson", "Grant", 
    "Jacob", "Sarah", "Ginger", "Josh", "Micayla", 
    "Colby", "Jed"
]

# Define the headers for the CSV
headers = ["id", "manager", "week_one", "week_two", "week_three", "week_four", "wins", "losses", "score"]

# Initialize a list to store each manager's data
data = []

print("Enter values for each manager:\n")

# Loop through each manager to get user input
for i, manager in enumerate(managers, start=1):
    print(f"Manager {manager} (ID: {i})")
    
    week_one = input("  Week 1 score: ")
    week_two = input("  Week 2 score: ")
    week_three = input("  Week 3 score: ")
    week_four = input("  Week 4 score: ")
    wins = input("  Wins: ")
    losses = input("  Losses: ")
    score = input("  Total Score: ")

    # Add the manager's data to the list
    data.append([i, manager, week_one, week_two, week_three, week_four, wins, losses, score])

# Specify the CSV filename
filename = "manager_metrics.csv"

# Write the data to a CSV file
with open(filename, mode='w', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(headers)  # Write the header row
    writer.writerows(data)    # Write all manager data

print(f"\nData saved to {filename}")
