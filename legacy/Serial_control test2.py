import serial
import time
import json
import math

# Serial ports
TFT_PORT = "/dev/TFT35"   # TFT35 connected via USB-to-TTL
SKR_PORT = "/dev/SKR"   # SKR 1.4 connected via USB 
LASER_PORT = "/dev/S_LASER" # Seeeduino Xiao connected via USB-C (Laser control)
INSTR_PORT = "/dev/S_INSTR" # Seeeduino Xiao connected via USB-C (Instrumentation)

# Initialize Serial Interfaces
tft_serial = serial.Serial(TFT_PORT, 115200, timeout=1)
skr_serial = serial.Serial(SKR_PORT, 115200, timeout=1)
laser_serial = serial.Serial(LASER_PORT, 115200, timeout=1)
instr_serial = serial.Serial(INSTR_PORT, 115200, timeout=1)
#instr_serial = None

# Calibration data storage
calibration_points = []  # Stores four corner positions
selected_lasers = []  # Stores user-selected lasers

# Define center XY positions for each laser (1-indexed for L1 to L6)
LASER_POSITIONS = {
    1: {"X": 79.6, "Y": 71.3},
    2: {"X": 75.6, "Y": 71.7},
    3: {"X": 75.0, "Y": 70.0},
    4: {"X": 49.4, "Y": 43.0},
    5: {"X": 49.4, "Y": 43.0},
    6: {"X": 50.0, "Y": 50.0},
}

# ------------------ Helper Functions ------------------

def send_to_tft(message):
    """Send a message to the TFT for user feedback."""
    print(f"Sending to TFT: {message}")
    tft_serial.write((message + "\n").encode())

def send_to_skr(command):
    """Send a command to the SKR for motion control."""
    print(f"Sending to SKR: {command}")
    skr_serial.write((command + "\n").encode())

def send_to_laser(command):
    """Send laser control commands to the Seeeduino Xiao."""
    print(f"Sending to Laser Controller: {command}")
    laser_serial.write((command + "\n").encode())

    while True:
        if laser_serial.in_waiting:
            msg = laser_serial.readline().decode().strip()
            print(msg)
        else:
            break

def send_to_instr(command):
    """Send instrumentation control commands to the Seeeduino Xiao."""
    print(f"Sending to Instrument Controller: {command}")
    #instr_serial.write((command + "\n").encode())

    while True:
        if instr_serial.in_waiting:
            msg = instr_serial.readline().decode().strip()
            print(msg)
        else:
            break

def process_tft_command(command):
    """Process incoming TFT commands and forward them appropriately."""
    command = command.strip()

    if command.startswith(("G", "M")):  

        if (command != "M105"):
            send_to_skr(command)  # Forward to SKR for motion control
    elif command.startswith("LASER"):  
        send_to_laser(command)  # Forward to laser controller
    elif command.startswith("L"):  
        selected_lasers.extend(list(command[1:]))  # Parse and store laser selection
        send_to_tft(f"Selected Lasers: {selected_lasers}")
    elif command == "OK":  
        return "OK"  # Used internally for confirmations
    else:
        send_to_tft("Unknown command")  # Inform user of an unrecognized command

def wait_for_user_confirmation():
    """Wait for an 'OK' command from the user via TFT while still handling movement commands."""
    while True:
        if tft_serial.in_waiting:
            command = tft_serial.readline().decode().strip()
            if command == "OK":
                return  # User confirmed the action
            else:
                process_tft_command(command)  # Forward movement commands in real-time
        if skr_serial.in_waiting:
            msg = skr_serial.readline().decode().strip()
            #print(msg)
        

def collect_corner_position(corner_name):
    """Prompt user to move to a corner while allowing manual adjustments."""
    send_to_tft(f"Move to {corner_name} corner using TFT, then press OK")

    # Keep processing movement commands while waiting for confirmation
    wait_for_user_confirmation()

    # Request and store the current position
    #send_to_skr("M114")  # Request current position
    while True:
        if skr_serial.in_waiting:
            position = skr_serial.readline().decode().strip()
            print(position)
            if position.startswith("X"):
                position_clean = position.split("Count")[0].strip()

                # Convert to dictionary: {'X': 77.0, 'Y': 52.0, ...}
                position_dict = {}
                for item in position_clean.split():
                    if ':' in item:
                        axis, value = item.split(':')
                        position_dict[axis] = float(value)

                calibration_points.append(position_dict)
                print(calibration_points)
                send_to_tft(f"Saved: {position_dict}")
                return

# ------------------ Main Routine ------------------

def home_and_calibrate():
    """Full calibration sequence including laser alignment."""
    send_to_tft("Homing all axes...")
    send_to_skr("G28")  # Home all axes
    time.sleep(60)  # Allow homing to complete
    send_to_skr("M154 S2")  # Enable position autoreport
    send_to_skr("G0 X60 Y60 A17.5 B17.5")

    send_to_tft("Turn on Laser 2 for alignment")
    send_to_laser("LASER 2")  # Turn on Laser 1

    # Collect all four corner positions
    for corner in ["first", "second", "third", "fourth"]:
        collect_corner_position(corner)

    send_to_tft("Calibration complete. Moving to perimeter check.")

    # Move along perimeter for user validation
    for point in calibration_points:
        print(point)
        gcode = "G0 " + " ".join(f"{k}{v:.3f}" for k, v in point.items())
        send_to_skr(gcode)
        print(gcode)
        time.sleep(10)

    send_to_tft("Does the perimeter look correct? Press OK")
    wait_for_user_confirmation()
    send_to_laser("LASER 0")  # Turn off all lasers

def select_lasers():
    """User selects which lasers to activate."""
    send_to_tft("Enter lasers to use (e.g., L123) and press OK")
    while True:
        if tft_serial.in_waiting:
            command = tft_serial.readline().decode().strip()
            if command.startswith("L"):
                selected_lasers.extend(list(command[1:]))
                send_to_tft(f"Selected Lasers: {selected_lasers}")
                return

def perform_ab_sweep(steps=10):
    def interpolate(p1, p2, t):
        return {
            "X": p1["X"] + t * (p2["X"] - p1["X"]),
            "Y": p1["Y"] + t * (p2["Y"] - p1["Y"])
        }

    p0, p1, p2, p3 = calibration_points  # Assume these are already in memory

    with open("combined_sweep_output.txt", "w") as f:
        f.write("X,Y,Value,Laser\n")
        
        for laser in selected_lasers:
            laser_num = int(laser)
            if laser_num not in LASER_POSITIONS:
                print(f"Laser {laser} position not defined. Skipping.")
                continue

            center = LASER_POSITIONS[laser_num]
            send_to_tft(f"Sweeping with Laser {laser}")
            send_to_laser(f"LASER {laser}")

            # Move XY to laser center before AB sweep
            send_to_skr(f"G0 X{center['X']} Y{center['Y']}")
            time.sleep(10)

            for row in range(steps):
                t_row = row / (steps - 1) if steps > 1 else 0
                start_edge = interpolate(p0, p3, t_row)
                end_edge = interpolate(p1, p2, t_row)

                for col in range(steps):
                    t_col = col / (steps - 1) if steps > 1 else 0
                    point = interpolate(start_edge, end_edge, t_col)

                    # Convert to AB space — assume laser center is (A=20, B=20)
                    rel_x = point["X"] - center["X"]
                    rel_y = point["Y"] - center["Y"]
                    A = 17.5 + rel_x
                    B = 17.5 + rel_y

                    # Constrain to AB range
                    if not (0 <= A <= 35 and 0 <= B <= 35):
                        continue

                    send_to_skr(f"G0 A{A:.2f} B{B:.2f}")
                    time.sleep(5)

                    send_to_instr("READ")
                    value = "SIMULATED_VALUE"  # Replace with real instrument reading
                    f.write(f"{point['X']:.2f},{point['Y']:.2f},{value},{laser}\n")

            send_to_laser("LASER 0")

    print("AB sweeps with multiple lasers written to combined_sweep_output.txt.")


# ------------------ Execution Loop ------------------

while True:
    if tft_serial.in_waiting:
        command = tft_serial.readline().decode().strip()
        process_tft_command(command)
    if skr_serial.in_waiting:
        command2 = skr_serial.readline().decode().strip()
    if(True):
        send_to_laser("LASER 0")  # Turn off all lasers
        send_to_tft("Start calibration? Press OK")
        wait_for_user_confirmation()
        home_and_calibrate()
        select_lasers()
        send_to_tft("Calibration complete. Ready for measurements.")
        perform_ab_sweep(steps = 10)
