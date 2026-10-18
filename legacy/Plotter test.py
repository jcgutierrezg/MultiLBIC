import matplotlib.pyplot as plt
import csv
from collections import defaultdict
from tkinter import Tk, filedialog
from matplotlib.widgets import CheckButtons

# === File selection dialog ===
root = Tk()
root.withdraw()
filename = filedialog.askopenfilename(
    title="Select sweep result file",
    filetypes=[("Text Files", "*.txt"), ("CSV Files", "*.csv"), ("All Files", "*.*")]
)

if not filename:
    print("No file selected.")
    exit()

# === Load data grouped by laser ===
data_by_laser = defaultdict(lambda: {"X": [], "Y": [], "Value": []})

with open(filename, "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            x = float(row["X"])
            y = float(row["Y"])
            val = float(row["Value"]) if row["Value"] != "SIMULATED_VALUE" else 0.0
            laser = row["Laser"]
            data_by_laser[laser]["X"].append(x)
            data_by_laser[laser]["Y"].append(y)
            data_by_laser[laser]["Value"].append(val)
        except ValueError:
            continue

# === Plotting ===
fig, ax = plt.subplots(figsize=(10, 8))
plt.subplots_adjust(left=0.25)  # Leave space for checkboxes

colors = ["red", "blue", "green", "purple", "orange", "cyan"]
laser_lines = {}
labels = []

# Create scatter plots for each laser
for i, (laser, data) in enumerate(sorted(data_by_laser.items())):
    color = colors[i % len(colors)]
    scatter = ax.scatter(data["X"], data["Y"], label=f"Laser {laser}", color=color, alpha=0.6)
    laser_lines[laser] = scatter
    labels.append(f"Laser {laser}")

# Set up plot
ax.set_xlabel("X (mm)")
ax.set_ylabel("Y (mm)")
ax.set_title("AB Sweep Result by Laser")
ax.axis("equal")
ax.grid(True)

# === Add checkbox widget ===
rax = plt.axes([0.03, 0.4, 0.15, 0.25])  # [left, bottom, width, height]
visibility = [True] * len(labels)
check = CheckButtons(rax, labels, visibility)

def toggle_laser_visibility(label):
    laser_id = label.split(" ")[-1]
    line = laser_lines.get(laser_id)
    if line:
        visible = not line.get_visible()
        line.set_visible(visible)
        plt.draw()

check.on_clicked(toggle_laser_visibility)

plt.show()
