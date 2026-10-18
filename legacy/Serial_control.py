import serial
import time
import threading
import random
from datetime import datetime

# Serial ports
TFT_PORT = "/dev/TFT35"
SKR_PORT = "/dev/SKR"
LASER_PORT = "/dev/S_LASER"
INSTR_PORT = "/dev/S_INSTR"

# Initialize Serial Interfaces
tft_serial = serial.Serial(TFT_PORT, 115200, timeout=1)
skr_serial = serial.Serial(SKR_PORT, 115200, timeout=1)
laser_serial = serial.Serial(LASER_PORT, 115200, timeout=1)
instr_serial = serial.Serial(INSTR_PORT, 115200, timeout=1)

# Calibration and parameters
calibration_point = None
selected_lasers = []
sample_size = {"X": 0.0, "Y": 0.0}
delta = 0.0

# Define center XY positions for each laser
LASER_POSITIONS = {
    1: {"X": 79.6, "Y": 71.3},
    2: {"X": 75.6, "Y": 71.7},
    3: {"X": 75.0, "Y": 70.0},
    4: {"X": 49.4, "Y": 43.0},
    5: {"X": 49.4, "Y": 43.0},
    6: {"X": 50.0, "Y": 50.0},
}

sweepFlag = False
sizeFlag = False
deltaFlag = False

# ------------------ Helper Functions ------------------

def send_to_tft(message):
    print(f"Sending to TFT: {message}")
    tft_serial.write((message + "\n").encode())

def send_to_skr(cmd, wait_for_ok=True):
    """
    Send a command to the SKR and optionally wait for a response.
    Returns the last non-empty line received.
    """
    if not skr_serial or not skr_serial.is_open:
        print("SKR serial not open.")
        return None

    cmd_str = cmd.strip() + "\n"
    skr_serial.write(cmd_str.encode("utf-8"))
    print(f"Sending to SKR: {cmd}")

    response = None
    if wait_for_ok:
        while True:
            line = skr_serial.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            print(f"SKR response: {line}")
            response = line
            if (line.lower().startswith("ok")) or "Count" in line or "A:" in line:
                break
    return response


def send_to_laser(command):
    print(f"Sending to Laser Controller: {command}")
    laser_serial.write((command + "\n").encode())
    while laser_serial.in_waiting:
        msg = laser_serial.readline().decode().strip()
        print(msg)

def send_to_instr(command):
    print(f"Sending to Instrument Controller: {command}")
    # instr_serial.write((command + "\n").encode())
    while instr_serial.in_waiting:
        msg = instr_serial.readline().decode().strip()
        print(msg)

def process_tft_command(command):
    """Process incoming TFT commands and forward them appropriately."""
    global sample_size, delta, sizeFlag, deltaFlag
    command = command.strip()

    if command.startswith(("G", "M")):
        if command != "M105":
            send_to_skr(command)

    elif command.startswith("LASER"):
        send_to_laser(command)

    elif command.startswith("L"):
        selected_lasers.extend(list(command[1:]))
        send_to_tft(f"Selected Lasers: {selected_lasers}")

    elif command.startswith("W"):  # Sample size definition
        try:
            parts = command[1:].split("X")
            sample_size["X"] = float(parts[0])
            sample_size["Y"] = float(parts[1])
            if sample_size["X"] >= 35.0 or sample_size["Y"] >= 35.0:
                send_to_tft("Sample too large for AB range (max 34mm)")
            else:
                send_to_tft(f"Sample size set: {sample_size['X']}x{sample_size['Y']} mm")
                sizeFlag = True
        except:
            send_to_tft("Invalid format. Use W1.00x1.00")

    elif command.startswith("D"):  # Delta definition
        try:
            delta = float(command[1:])
            if(delta>0):
                send_to_tft(f"Delta set: {delta} mm")
                deltaFlag = True
            else:
                send_to_tft("Invalid delta. Must be greater than 0")
        except:
            send_to_tft("Invalid format. Use D0.01")

    elif command == "OK":
        return "OK"

    else:
        send_to_tft("Unknown command")

def wait_for_user_confirmation():
    while True:
        if tft_serial.in_waiting:
            command = tft_serial.readline().decode().strip()
            if command == "OK":
                return
            else:
                process_tft_command(command)
        if skr_serial.in_waiting:
            _ = skr_serial.readline().decode().strip()

def collect_corner_position():
    """Calibrate using only the top-right corner."""
    global calibration_point

    send_to_tft("Move to TOP-RIGHT corner, then press OK")
    wait_for_user_confirmation()

    # Explicitly request the current position from SKR
    #send_to_skr("M114")

    # Wait for SKR to reply with a position
    while True:
        response = send_to_skr("M114")
        if response.startswith("X"):
            # Strip everything after "Count" to avoid duplicates
            response = response.split("Count")[0].strip()

            # Parse into dictionary
            position_dict = {}
            for item in response.split():
                if ':' in item:
                    axis, value = item.split(':')
                    try:
                        position_dict[axis] = float(value)
                    except ValueError:
                        continue

            calibration_point = position_dict
            send_to_tft(f"Saved calibration: {position_dict}")
            return


def request_user_parameters():
    """Force user to input W and D commands before calibration."""
    global sample_size, delta, sizeFlag, deltaFlag

    while not sizeFlag:
        send_to_tft("Enter sample size (W1.00x1.00)")
        wait_for_user_confirmation()
    while not deltaFlag:
        send_to_tft("Enter delta (D0.01)")
        wait_for_user_confirmation()

def get_current_position():
    """Query SKR for current position using M114 and parse the response."""
    response = send_to_skr("M114")
    pos = {}
    if not response:
        return pos

    # Ignore everything after 'Count'
    if "Count" in response:
        response = response.split("Count")[0].strip()

    try:
        for token in response.split():
            if ":" in token:
                axis, value = token.split(":")
                if axis in ["X", "Y", "Z", "A", "B", "E"]:
                    pos[axis] = float(value)
    except Exception:
        print(f"Failed to parse M114: {response}")
    return pos



def wait_for_move_completion2():
    """Wait until SKR has finished executing all queued moves and measure during the move."""
    global sweepFlag

    measured_values = []
    lastTime = int(time.time() * 1000)

    doneFlag = False
    while not doneFlag:
        response = send_to_skr("M400")

        if sweepFlag:
            # Simulated read - replace this with real instrument read
            print("value stored")
            send_to_instr("READ")
            value = "SIMULATED_VALUE"  # <-- Replace with actual SMU read
            timestamp = int(time.time() * 1000)  # Timestamp in ms

            deltaTime = timestamp-lastTime

            measured_values.append((value, deltaTime))
            lastTime = timestamp

        if response.startswith("ok"):
            doneFlag = True
            sweepFlag = False

        # Optional: slow down polling loop if it's too fast
        #time.sleep(0.01)  # 10ms between checks

    return measured_values

def wait_for_move_completion():
    """Wait until SKR has finished executing all queued moves and measure during the move."""
    global sweepFlag

    measured_values = []

    # Only start thread if in sweep mode
    if sweepFlag:
        stop_event = threading.Event()
        lock = threading.Lock()
        poll_thread = threading.Thread(target=instrument_polling, args=(stop_event, measured_values, lock))
        poll_thread.start()

    # Wait for SKR to finish movement
    while True:
        response = send_to_skr("M400")
        if response and response.startswith("ok"):
            break
        time.sleep(0.01)  # Avoid tight loop

    if sweepFlag:
        stop_event.set()
        poll_thread.join()
        sweepFlag = False

    return measured_values




def home_and_calibrate():
    """Home, calibrate one corner, adjust XY to sample center, confirm perimeter."""
    global calibration_point, w, h, Xoffset, Yoffset
    send_to_tft("Homing all axes...")
    send_to_skr("G28")
    wait_for_move_completion()
    send_to_skr("M154 S0")

    send_to_skr("G0 X60 Y60 A17.5 B17.5 F360")

    send_to_tft("Turn on Laser 2 for alignment")
    send_to_laser("LASER 2")  # Turn on Laser 2

    collect_corner_position()

    if calibration_point:
        Xcal = calibration_point["X"]
        Ycal = calibration_point["Y"]

        # Move XY to sample center
        Xcenter = Xcal + (sample_size["X"] / 2)
        Ycenter = Ycal + (sample_size["Y"] / 2)
        send_to_skr(f"G0 X{Xcenter:.2f} Y{Ycenter:.2f}")
        send_to_tft(f"Sample centered at X{Xcenter:.2f} Y{Ycenter:.2f}")

        Xoffset = LASER_POSITIONS[2]["X"]-Xcenter
        Yoffset = LASER_POSITIONS[2]["Y"]-Ycenter

        print(f"Xoffset: {Xoffset}, Yoffset: {Yoffset}")

        # --- AB Perimeter Check ---
        w = sample_size["X"]
        h = sample_size["Y"]

        send_to_tft("Testing AB perimeter with laser ON...")
        send_to_laser("LASER 2")  # test laser only

        # Center of AB stage
        A0, B0 = 17.5, 17.5

        # Define corners around AB center
        corners = [
            (A0 - w/2, B0 - h/2),  # bottom-left
            (A0 + w/2, B0 - h/2),  # bottom-right
            (A0 + w/2, B0 + h/2),  # top-right
            (A0 - w/2, B0 + h/2),  # top-left
            (A0 - w/2, B0 - h/2),  # close loop
        ]

        for (a, b) in corners:
            send_to_skr(f"G0 A{a:.2f} B{b:.2f} F360")
            wait_for_move_completion()
            #time.sleep(1)

        send_to_tft("Does the perimeter look correct? Press OK")
        wait_for_user_confirmation()
        send_to_laser("LASER 0")


def select_lasers():
    send_to_tft("Enter lasers to use (e.g., L123) and press OK")
    while True:
        if tft_serial.in_waiting:
            command = tft_serial.readline().decode().strip()
            if command.startswith("L"):
                selected_lasers.extend(list(command[1:]))
                send_to_tft(f"Selected Lasers: {selected_lasers}")
                return

def perform_ab_sweep():

    global calibration_point, w, h, delta, Xoffset, Yoffset, sweepFlag

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"combined_sweep_output_{timestamp}.txt"

    with open(filename, "w") as f:
        f.write("X,Y,Value,Time,Laser\n")
        
        for laser in selected_lasers:
            laser_num = int(laser)
            if laser_num not in LASER_POSITIONS:
                print(f"Laser {laser} position not defined. Skipping.")
                continue

            sweepFlag = False

            laser_centerX = LASER_POSITIONS[laser_num]["X"] - Xoffset
            laser_centerY = LASER_POSITIONS[laser_num]["Y"] - Yoffset

            send_to_tft(f"Sweeping with Laser {laser}")
            send_to_laser(f"LASER {laser}")

            time.sleep(3)

            # Move XY to laser center before AB sweep
            send_to_skr(f"G0 X{laser_centerX} Y{laser_centerY}")

            x1 = 17.5 - w/2
            x2 = 17.5 + w/2
            y1 = 17.5 - h/2
            y2 = 17.5 + h/2

            N = round((y2-y1)/delta)
            print(f"N:{N}")

            #send_to_tft("Turn on Laser 2")
            #send_to_laser("LASER 2")  # Turn on Laser 1

            send_to_skr(f"G0 A{x1:.2f} B{y1:.2f}")
            send_to_tft(f"Sample corner at A{x1:.2f} B{y1:.2f}")

            wait_for_move_completion()

            i = 0
            n = 1

            while(i<N):
                print(f"n:{n}")
                if(n==1 or n==2):
                    x_i = x2
                if(n==3 or n==4):
                    x_i = x1
                y_i = y1 + i*delta

                send_to_skr(f"G0 A{x_i:.2f} B{y_i:.2f} F360")
                send_to_tft(f"Moving to: A{x_i:.2f} B{y_i:.2f}")

                if(n==1 or n==3):
                    i+=1
                    sweepFlag = True
                if(n==4):
                    n=1
                else:
                    n+=1
                # Wait for move to complete and collect measurements
                measurements = wait_for_move_completion()

                # Write all measurements taken during this move
                for value, timestamp in measurements:
                    x_abs = x_i-x1
                    y_abs = y_i-y1
                    f.write(f"{x_abs:.2f},{y_abs:.2f},{value},{timestamp},{laser}\n")

            send_to_laser("LASER 0")
            pass

def instrument_polling(stop_event, measured_values, lock):
    """Poll the instrument while the stop_event is not set."""
    last_time = int(time.time() * 1000)

    while not stop_event.is_set():
        send_to_instr("READ")
        value = round(random.uniform(0.0, 10.0), 4)  # Replace this with actual value from SMU

        timestamp = int(time.time() * 1000)
        delta_time = timestamp - last_time
        last_time = timestamp
        print(delta_time)

        # Store the value and timestamp thread-safely
        with lock:
            measured_values.append((value, delta_time))

        time.sleep(0.001)  # Polling interval (10ms, adjust as needed)

# ------------------ Execution Loop ------------------

while True:
    if tft_serial.in_waiting:
        command = tft_serial.readline().decode().strip()
        process_tft_command(command)
    if skr_serial.in_waiting:
        _ = skr_serial.readline().decode().strip()
    if True:
        send_to_laser("LASER 0")
        request_user_parameters()   # <--- force W and D before calibration
        send_to_tft("Start calibration? Press OK")
        wait_for_user_confirmation()
        home_and_calibrate()
        select_lasers()
        send_to_tft("Calibration complete. Ready for measurements.")
        perform_ab_sweep()
