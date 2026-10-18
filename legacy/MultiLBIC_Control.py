
## Imports and libraries

import serial
import time
import threading
import random
from datetime import datetime

import csv
from tqdm import tqdm

import queue
import math

import os
from pathlib import Path
import sys
import numpy as np

import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
from tkinter import font as tkfont

from matplotlib.figure import Figure 
from matplotlib.backends.backend_tkagg import (FigureCanvasTkAgg,  
NavigationToolbar2Tk)

from collections import deque

from minismu_py import SMU, ConnectionType

## Parameters

window_size = "1200x1000"
window_title = "MultiLBIC Control"

backgndColor = "#151716"
highlightbackColor = "#404040"
yellowColor = "#cfc213"
butTextColor = "black"
redColor = "#e36868"
greenColor = "#7de368"
blueColor = "#6873e3"
cyanColor = "#20D0E0"
purpleColor = "#9020D0"

# Serial ports
TFT_PORT = "/dev/TFT35"
SKR_PORT = "/dev/SKR"
LASER_PORT = "/dev/S_LASER"
INSTR_PORT = "/dev/S_INSTR"
SMU_PORT = ""

tft_serial = None
skr_serial = None
laser_serial = None
instr_serial = None

smu = None

## Global variables

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

# Calibration and parameters
calibration_point = None
selected_lasers = []
delta = 0.0
um_per_pixel = 1000
run_name = ""
SMU_bias = 0.0
w = 0.0
h = 0.0

canvas = None
fig = None
toolbar = None
arr_flag = False

curr_mem = []
volt_mem = []
dataset_mem = []
counter_mem = -1

move_resolution = "1"
xyab_mode = "xy"

allSerialCheck = False


# ---------- CONFIG / TUNABLE ----------
SMU_CHANNEL = 1
SMU_SAMPLE_RATE_HZ = 1000  # set to your SMU streaming rate (100..1000)
SMU_PREBUFFER_SECONDS = 0.02
SAMPLE_QUEUE_MAX = 200000    # adjust based on memory and expected row duration
WRITE_QUEUE_MAX = 200000
READER_DRAIN_TIMEOUT_S = 2.0
# --------------------------------------

def map_timestamp_to_x_ms(ts_ms, motion_start_ms, x_start, x_end, feed_mm_per_min):
    """Map SMU timestamp (ms) to an X position assuming constant velocity."""
    feed_mm_s = feed_mm_per_min / 60.0
    total_dist = abs(x_end - x_start)
    if feed_mm_s <= 0 or total_dist == 0:
        return x_start
    total_time_s = total_dist / feed_mm_s
    total_time_ms = total_time_s * 1000.0
    elapsed_ms = ts_ms - motion_start_ms
    frac = max(0.0, min(1.0, elapsed_ms / total_time_ms))
    return (x_start + frac * total_dist) if x_end >= x_start else (x_start - frac * total_dist)

def smu_stream_reader(smu, channel, out_q, stop_event, read_timeout_ms=200):
    """
    Continuously read streaming data from SMU and put (t_ms, voltage, current) into out_q.
    Adjust the smu.read_streaming_data() call to match your real API.
    """
    try:
        while not stop_event.is_set():
            try:
                # Example API: returns (channel, timestamp_ms, voltage, current)
                data = smu.read_streaming_data(timeout_ms=read_timeout_ms)
                if data is None:
                    continue
                data_channel, t_ms, v, i_val = data
                if data_channel == channel:
                    try:
                        out_q.put_nowait((t_ms, v, i_val))
                    except queue.Full:
                        # Queue overflow — dropping newest sample; warn once
                        # Consider enlarging queue or handling backpressure if this occurs.
                        print("Warning: sample queue full — dropping SMU sample")
                        continue
            except Exception as e:
                # transient read error: log and continue (do not kill thread)
                print(f"smu_stream_reader read error: {e}")
                time.sleep(0.001)
    finally:
        return

def disk_writer_thread(write_q, stop_event, out_fh):
    """
    Pulls tuples (x_mm, y_mm, value, ts_ms, laser_id) from write_q and writes CSV lines.
    """
    while not (stop_event.is_set() and write_q.empty()):
        try:
            item = write_q.get(timeout=0.1)
        except queue.Empty:
            continue
        try:
            x_mm, y_mm, value, ts_ms, laser_id = item
            out_fh.write(f"{x_mm:.6f},{y_mm:.6f},{value},{ts_ms},{laser_id}\n")
        except Exception as e:
            print(f"disk_writer_thread write error: {e}")
        finally:
            write_q.task_done()

def continuous_x_traverse_with_threaded_stream(
    smu,
    smu_channel,
    x_start,
    x_end,
    y,
    feed_mm_per_min,
    laser_id,
    out_file_handle,
    sample_q_max=SAMPLE_QUEUE_MAX,
    write_q_max=WRITE_QUEUE_MAX,
    sample_rate_hz=SMU_SAMPLE_RATE_HZ,
    prebuffer_seconds=SMU_PREBUFFER_SECONDS,
    reader_drain_timeout_s=READER_DRAIN_TIMEOUT_S
):
    """
    - Start SMU streaming + reader + writer threads
    - Issue continuous G1 move from x_start->x_end at y with feed
    - Wait for motion completion, stop streaming, drain samples
    - Map SMU timestamps -> X and enqueue writes
    - Return number of samples processed
    """

    # Configure SMU sampling rate (caller should have set mode/voltage)
    smu.set_sample_rate(smu_channel=smu_channel, sample_rate=sample_rate_hz) if False else None
    # NOTE: above line is placeholder to remind you to set sample rate if required.
    # In many APIs you would call: smu.set_sample_rate(smu_channel, sample_rate_hz)

    # Create queues and control events
    sample_q = queue.Queue(maxsize=sample_q_max)
    write_q = queue.Queue(maxsize=write_q_max)
    stop_reader = threading.Event()
    stop_writer = threading.Event()

    # Start writer thread (writing to already-open file handle)
    writer = threading.Thread(target=disk_writer_thread, args=(write_q, stop_writer, out_file_handle), daemon=True)
    writer.start()

    # Sync SMU clock to host (ms) as close as possible to issuing motion
    host_now_ms = int(time.time() * 1000)
    try:
        smu.set_time(host_now_ms)
    except Exception as e:
        print(f"Warning: smu.set_time() failed: {e}")

    # Start streaming on device
    smu.set_sample_rate(smu_channel, sample_rate_hz)   # actual API
    smu.start_streaming(smu_channel)

    # Start reader thread
    reader = threading.Thread(target=smu_stream_reader, args=(smu, smu_channel, sample_q, stop_reader), daemon=True)
    reader.start()

    # Allow small prebuffer so streaming stabilizes
    time.sleep(prebuffer_seconds)

    # Record host-side motion start time as close as possible to sending G1
    motion_start_host_ms = int(time.time() * 1000)

    # Issue continuous motion command
    send_to_skr(f"G1 A{x_end:.6f} B{y:.6f} F{feed_mm_per_min:.3f}")

    # Wait for motion completion (blocks)
    wait_for_move_completion()

    # Motion finished; stop streaming
    try:
        smu.stop_streaming(smu_channel)
    except Exception as e:
        print(f"Warning: smu.stop_streaming() failed: {e}")

    # Give reader short time to pull out buffered packets
    drain_start = time.time()
    while time.time() - drain_start < reader_drain_timeout_s:
        # if sample_q is being filled, give it time; break early if empty
        if sample_q.empty():
            break
        time.sleep(0.01)

    # Signal reader to stop and join
    stop_reader.set()
    reader.join(timeout=1.0)

    # Drain sample_q into a list for mapping
    samples = []
    while True:
        try:
            t_ms, v, i_val = sample_q.get_nowait()
        except queue.Empty:
            break
        samples.append((t_ms, v, i_val))

    # Map timestamps to X positions and enqueue write tasks
    for t_ms, v, i_val in samples:
        x_pos = map_timestamp_to_x_ms(t_ms, motion_start_host_ms, x_start, x_end, feed_mm_per_min)
        # Put absolute coordinates; we'll subtract x1/y1 when writing if you prefer relative coords
        # queue will block if writer is too slow; consider larger writer queue or non-blocking put
        write_q.put((x_pos, y, v, t_ms, laser_id))

    # Wait for all writes to finish
    write_q.join()
    stop_writer.set()
    writer.join(timeout=1.0)

    return len(samples)

def send_to_tft(message):
    print(f"Sending to TFT: {message}")
    terminal.writeln(f"Sending to TFT: {message}", tag="out")
    #tft_serial.write((message + "\n").encode()) # type: ignore

def send_to_skr(cmd, wait_for_ok=True):
    """
    Send a command to the SKR and optionally wait for a response.
    Returns the last non-empty line received.
    """
    if not skr_serial or not skr_serial.is_open:
        print("SKR serial not open.")
        terminal.writeln("SKR serial not open.", tag="err")
        return None

    cmd_str = cmd.strip() + "\n"
    skr_serial.write(cmd_str.encode("utf-8"))
    print(f"Sending to SKR: {cmd}")
    terminal.writeln(f"Sending to SKR: {cmd}", tag="out")

    response = None
    if wait_for_ok:
        while True:
            line = skr_serial.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            print(f"SKR response: {line}")
            terminal.writeln(f"SKR response: {line}", tag="in")
            response = line
            if (line.lower().startswith("ok")) or "Count" in line or "A:" in line:
                break
    return response


def send_to_laser(command):
    print(f"Sending to Laser Controller: {command}")
    terminal.writeln(f"Sending to Laser Controller: {command}", tag="out")
    #laser_serial.write((command + "\n").encode()) # type: ignore
    #while laser_serial.in_waiting: # type: ignore
    #    msg = laser_serial.readline().decode().strip() # type: ignore
    #    print(msg)

def send_to_instr(command):
    print(f"Sending to Instrument Controller: {command}")
    terminal.writeln(f"Sending to Instrument Controller: {command}", tag="out")
    # instr_serial.write((command + "\n").encode())
    #while instr_serial.in_waiting: # type: ignore
    #    msg = instr_serial.readline().decode().strip() # type: ignore
    #    print(msg)


def collect_corner_position():
    """Calibrate using only the top-right corner."""
    global calibration_point

    # Explicitly request the current position from SKR
    #send_to_skr("M114")

    if allSerialCheck:

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
        
def stream_data(smu, channel=1, duration=10.0, sample_rate=100.0, voltage=3.3):
    """Stream data from the SMU for a specified duration"""
    try:
        # Configure channel
        smu.set_mode(channel, "FVMI")
        smu.enable_channel(channel)
        smu.set_voltage(channel, voltage)
        
        # Configure streaming
        smu.set_sample_rate(channel, sample_rate)
        
        # Set miniSMU's internal time for timestamping
        current_time = int(time.time() * 1000)  # Convert to milliseconds
        smu.set_time(current_time)
        
        # Calculate number of samples
        num_samples = int(duration * sample_rate)
        
        # Prepare data storage
        timestamps = []
        voltages = []
        currents = []
        
        # Start streaming
        print("Starting streaming...")
        smu.start_streaming(channel)
        
        # Collect data with progress bar
        pbar = tqdm(total=num_samples, desc="Streaming Data")
        while len(timestamps) < num_samples:
            try:
                # Read streaming data packet
                data_channel, t, v, i = smu.read_streaming_data()
                
                # Only process data from the requested channel
                if data_channel == channel:
                    timestamps.append(t)
                    voltages.append(v)
                    currents.append(i)
                    pbar.update(1)
                
            except Exception as e:
                print(f"\nError reading streaming data: {e}")
                break
        
        # Stop streaming
        smu.stop_streaming(channel)
        pbar.close()
        
        # Save data to CSV
        filename = f'streaming_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Timestamp (s)', 'Voltage (V)', 'Current (A)'])
            for t, v, i in zip(timestamps, voltages, currents):
                writer.writerow([t, v, i])
        
        print(f"Data saved to {filename}")
        return timestamps, voltages, currents
            
    finally:
        # Always cleanup
        smu.disable_channel(channel)
        smu.stop_streaming(channel)

# # Stream data for 5 seconds at 100Hz
# with SMU(ConnectionType.USB, port="COM3") as smu:
#     timestamps, voltages, currents = stream_data(
#         smu, 
#         channel=1,
#         duration=5.0,
#         sample_rate=100.0,
#         voltage=3.3
#     )
        
def sweep():

    global sweepFlag

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"MultiLBIC_{run_name}_{timestamp}.txt"

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

def sweep2():
    global sweepFlag

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"MultiLBIC_{run_name}_{timestamp}.txt"
    pixel_pitch_mm = um_per_pixel / 1000.0
    if pixel_pitch_mm <= 0:
        raise ValueError("um_per_pixel must be > 0")

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
            send_to_skr(f"G0 X{laser_centerX} Y{laser_centerY}")

            x1 = 17.5 - w/2
            x2 = 17.5 + w/2
            y1 = 17.5 - h/2
            y2 = 17.5 + h/2

            Ny = int(round(h / pixel_pitch_mm))
            Ny = max(1, Ny)

            used_span = Ny * pixel_pitch_mm
            extra_space = h - used_span
            first_center_offset = extra_space / 2.0  # mm

            print(f"pixel_pitch_mm: {pixel_pitch_mm:.6f} mm, Ny: {Ny}")
            send_to_tft(f"Sample corner at A{x1:.2f} B{y1:.2f} (rows: {Ny})")

            # move to starting corner
            send_to_skr(f"G0 A{x1:.2f} B{y1:.2f}")
            wait_for_move_completion()

            i = 0
            n = 1

            while i < Ny:
                print(f"n:{n} i:{i}")
                if n == 1 or n == 2:
                    x_i = x2
                else:
                    x_i = x1

                # compute y center on-the-fly (no list)
                y_i = y1 + first_center_offset + (pixel_pitch_mm / 2.0) + i * pixel_pitch_mm

                send_to_skr(f"G0 A{x_i:.2f} B{y_i:.2f} F360")
                send_to_tft(f"Moving to: A{x_i:.2f} B{y_i:.2f}")

                if n == 1 or n == 3:
                    # these are X traversals where you want measurements

                    # perform continuous X traverse and streaming capture
                    num_samples = continuous_x_traverse_with_threaded_stream(
                        smu=smu,
                        smu_channel=1,
                        x_start=current_x_start,   # this depends on direction
                        x_end=current_x_end,
                        y=y_i,
                        feed_mm_per_min=feed_value,
                        sample_rate_hz=sample_rate,
                        laser_id=laser,
                        out_file_handle=outfile_handle  # open before loop
                    )

                    i += 1
                    sweepFlag = True
                else:
                    sweepFlag = False

                # advance n cycle
                n = 1 if n == 4 else n + 1

                # Wait for move completion and collect measurements (existing function)
                measurements = wait_for_move_completion()

                # write measurements relative to sample origin
                for value, ts in measurements:
                    x_abs = x_i - x1
                    y_abs = y_i - y1
                    f.write(f"{x_abs:.2f},{y_abs:.2f},{value},{ts},{laser}\n")

            send_to_laser("LASER 0")
            sweepFlag = False

def sweep3(smu):
    """
    Integrated sweep:
    - smu: an opened SMU instance (connected), matching the streaming API used above.
    """

    global sweepFlag

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"MultiLBIC_{run_name}_{timestamp}.txt"

    pixel_pitch_mm = um_per_pixel / 1000.0
    if pixel_pitch_mm <= 0:
        raise ValueError("um_per_pixel must be > 0")

    # Open file once and share handle with writer threads
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

            # number of pixel-rows in Y (Ny)
            Ny = int(round(h / pixel_pitch_mm))
            Ny = max(1, Ny)

            used_span = Ny * pixel_pitch_mm
            extra_space = h - used_span
            first_center_offset = extra_space / 2.0  # mm

            print(f"pixel_pitch_mm: {pixel_pitch_mm:.6f} mm, Ny: {Ny}")
            send_to_tft(f"Sample corner at A{x1:.2f} B{y1:.2f} (rows: {Ny})")

            # move to starting corner
            send_to_skr(f"G0 A{x1:.2f} B{y1:.2f}")
            wait_for_move_completion()

            i = 0
            n = 1

            # Outer while keeping your 4-step n-cycle logic
            while i < Ny:
                print(f"n:{n} i:{i}")
                # Determine X target (ends of sample)
                if n == 1 or n == 2:
                    x_i = x2
                    x_start_for_traverse = x1   # we will traverse from x1 -> x2
                    x_end_for_traverse = x2
                else:
                    x_i = x1
                    x_start_for_traverse = x2   # traverse from x2 -> x1
                    x_end_for_traverse = x1

                # compute y center on-the-fly
                y_i = y1 + first_center_offset + (pixel_pitch_mm / 2.0) + i * pixel_pitch_mm

                # If this move is an X-traversal where you want measurements (n==1 or n==3)
                if n == 1 or n == 3:
                    # Start continuous traversal while capturing streamed data in threads
                    sweepFlag = True

                    # Call the threaded streaming traverse helper:
                    num_samples = continuous_x_traverse_with_threaded_stream(
                        smu=smu,
                        smu_channel=SMU_CHANNEL,
                        x_start=x_start_for_traverse,
                        x_end=x_end_for_traverse,
                        y=y_i,
                        feed_mm_per_min=360,        # <- set feed appropriately or make it a parameter
                        sample_rate_hz=SMU_SAMPLE_RATE_HZ,
                        laser_id=laser,
                        out_file_handle=f,         # file handle for writer thread
                        sample_q_max=SAMPLE_QUEUE_MAX,
                        write_q_max=WRITE_QUEUE_MAX,
                        prebuffer_seconds=SMU_PREBUFFER_SECONDS,
                        reader_drain_timeout_s=READER_DRAIN_TIMEOUT_S
                    )
                    # After function returns, the mapped samples are already written to file by writer thread.
                    i += 1  # advance row counter after a full X traversal (as in your original logic)

                else:
                    # Y reposition move (no measurement)
                    sweepFlag = False
                    # Move to the corner X (x_i) and the Y center y_i
                    send_to_skr(f"G0 A{x_i:.2f} B{y_i:.2f} F360")
                    send_to_tft(f"Moving to: A{x_i:.2f} B{y_i:.2f}")
                    # wait and do not record measurements
                    wait_for_move_completion()

                # advance n cycle (wrap 4 -> 1)
                n = 1 if n == 4 else n + 1

            # Turn off laser after finishing sample
            send_to_laser("LASER 0")
            sweepFlag = False

    # file closed automatically
    return

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

def plot(overlap): 
    # Define the global variables used in the function
    global canvas, toolbar, fig, graph_title, counter_mem, curr_mem, volt_mem, dataset_mem
  
    # Create a new figure object with specified size and resolution
    fig = Figure(figsize=(6, 6), dpi=100) 
    
    # Add a subplot to the figure (1 row, 1 column, 1st plot)
    plot1 = fig.add_subplot(111) 

    # Check if overlapping of previous plots is desired and there are previous plots
    if overlap and counter_mem > 0:
        # Loop through each set of data up to counter_mem and plot each set with markers
        for i in range(counter_mem + 1):
            plot1.plot(volt_mem[i], curr_mem[i], 'o', label=dataset_mem[i])
    else:
        # Plot only the most recent data set with markers
        plot1.plot(volt_mem[counter_mem], curr_mem[counter_mem], 'o', label=dataset_mem[counter_mem]) 

    # Set the title and labels for the plot using the values from the graph_title object
    plot1.set(title=graph_title.get_value(), xlabel="Voltage [V]", ylabel="Current [A]")
    # Add a legend to the plot in the upper left corner
    plot1.legend(loc="upper left")

    # Create a canvas object to display the figure in the Tkinter window
    canvas = FigureCanvasTkAgg(fig, master=root)   
    # Draw the canvas
    canvas.draw() 

    # Place the canvas widget at a specific position within the root window
    canvas.get_tk_widget().place(x=50, y=10)

    # Create a toolbar for navigating the plot (zoom, pan, etc.)
    toolbar = NavigationToolbar2Tk(canvas, root, pack_toolbar=False)
    # Place the toolbar widget at a specific position within the root window
    toolbar.place(x=140, y=620) 
    # Update the toolbar to reflect the current state of the canvas
    toolbar.update() 

def read_current(vbias):
    """Perform a voltage sweep and measure current"""
    global smu
    channel = 1
    try:
        # Configure channel
        smu.set_mode(channel, "FVMI")
        smu.set_voltage_range(channel, "AUTO")
        smu.enable_channel(channel)

        smu.set_voltage(channel, vbias)
        
        # # Create voltage points
        # voltages = [round(v, 3) for v in 
        #            [start + step*i for i in range(int((stop-start)/step) + 1)]]
        # results = []
        
        # # Create progress bar
        # for voltage in tqdm(voltages, desc="Voltage Sweep"):
        #     smu.set_voltage(channel, voltage)
        #     time.sleep(0.1)  # Allow settling time
        #     v, i = smu.measure_voltage_and_current(channel)
        #     results.append({
        #         'target_voltage': voltage,
        #         'measured_voltage': v,
        #         'measured_current': i
        #     })
        voltage = smu.measure_voltage(channel)
        print(voltage)
        current = smu.measure_current(channel)
        
        return current
            
    finally:
        # Always disable channel after measurement
        smu.disable_channel(channel)
    
## BUTTON ACTIVATIONS 

def save_func():
    # Define global variables used in the function
    global volt_mem, curr_mem, counter_mem, dataset_mem

    # Initialize an empty list to hold the arrays
    arrays = []

    # Loop over the range of counter_mem + 1 to get all voltage and current measurements
    for i in range(counter_mem + 1):
        # Append voltage and current arrays to the list
        arrays.append(volt_mem[i])
        arrays.append(curr_mem[i])

    # Find the maximum length of the arrays to determine the padding needed
    max_length = max(len(array) for array in arrays)

    # Initialize a list to hold the padded arrays
    padded_arrays = []
    for array in arrays:
        # Calculate the padding length required
        padding_length = max_length - len(array)
        # Pad the array with NaN values to make all arrays the same length
        padded_array = np.pad(array, (0, padding_length), mode='constant', constant_values=np.nan)
        padded_arrays.append(padded_array)

    # Initialize a list to hold the columns for the final array
    columns = []

    # Loop over the padded arrays two at a time, for voltage and current
    for i in range(0, len(padded_arrays), 2):
        # Add the voltage and current arrays to the columns list
        columns.append(padded_arrays[i])
        if i + 1 < len(padded_arrays):
            columns.append(padded_arrays[i + 1])
        # Add an empty column (filled with NaN) after each pair, if not the last pair
        if i + 2 < len(padded_arrays):
            empty_col = np.full(max_length, np.nan)
            columns.append(empty_col)

    # Combine the columns into a single array with each array as a column
    combined_array = np.column_stack(columns)

    # Initialize the header list for the CSV file
    header = []
    for i in range(counter_mem + 1):
        # Add headers for voltage and current columns
        header.append(f'Voltage [V] {i + 1}: {dataset_mem[i]}')
        if i + 1 < len(padded_arrays):
            header.append(f'Current [A] {i + 1}: {dataset_mem[i]}')
        # Add an empty header after each pair, if not the last pair
        if i + 2 < len(padded_arrays):
            header.append('')

    # Open a file dialog to get the save location from the user
    file_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])

    # If a file path is selected, save the combined array to the CSV file with the header
    if file_path:
        np.savetxt(file_path, combined_array, delimiter=',', header=','.join(header), comments='', fmt='%s')

        # Change the background color of the save button to indicate success
        save_button['bg'] = greenColor

        # Update the message label to inform the user that the data has been saved
        msg_label.config(text='Data saved to file')


def clear_func():

    global volt_mem, curr_mem, counter_mem, dataset_mem

    # Clear all memory arrays of previous measurements
    volt_mem = []
    curr_mem = []
    dataset_mem = []
    counter_mem = -1


    if(counter_mem == -1):

        save_button['state'] = 'disabled'
        new_button['state'] = 'disabled'
        
        save_button['bg'] = redColor
        new_button['bg'] = redColor


def init_ports_func():

    global tft_serial, skr_serial, laser_serial, instr_serial, smu, allSerialCheck

    try:

        # Initialize Serial Interfaces
        skr_serial = serial.Serial(SKR_PORT, 115200, timeout=1)
        canvas_skr.itemconfig(circle_skr, fill="#00FF00")
    
        tft_serial = serial.Serial(TFT_PORT, 115200, timeout=1)
        canvas_lcd.itemconfig(circle_lcd, fill="#00FF00")

        laser_serial = serial.Serial(LASER_PORT, 115200, timeout=1)
        canvas_las.itemconfig(circle_las, fill="#00FF00")

        #instr_serial = serial.Serial(INSTR_PORT, 115200, timeout=1)
        #canvas_skr.itemconfig(circle_skr, fill="#00FF00")

        smu = SMU(ConnectionType.USB, port=SMU_PORT)
        canvas_smu.itemconfig(circle_smu, fill="#00FF00")

        terminal.writeln("All devices connected successfully", tag="out")
        time.sleep(1)
        terminal.writeln("Please enter your sample name, specs and pixel resolution. When you're done, press -Home axis-", tag="out")

        home_button["state"] = 'normal'
        l1_on_button['state'] = 'normal'
        l2_on_button['state'] = 'normal'
        l3_on_button['state'] = 'normal'
        l4_on_button['state'] = 'normal'
        l5_on_button['state'] = 'normal'
        l6_on_button['state'] = 'normal'

        for btn in xy_buttons.values():
                btn.config(state='normal')

        tog01_button['state'] = 'normal'
        tog1_button['state'] = 'normal'
        tog10_button['state'] = 'normal'
        torque_button['state'] = 'normal'

        allSerialCheck = True

    except Exception as e:

        terminal.writeln(str(e), tag="err")

def plot_select_func(laser_number):

    print(laser_number)

def how_to_func():

    print("how-to")

def laser_toggle(laser):

    #print(laser)

    send_to_laser("LASER 0")
    time.sleep(2)
    send_to_laser(laser)

def xy_func(cardinality):

    global xyab_mode

    send_to_skr("G91")

    msg = None

    if(xyab_mode == "xy"):

        if(cardinality == "XY/AB"):

            xyab_mode = "ab"
            xy_buttons["XY/AB"].config(text="AB")
            for btn in xy_buttons.values():
                btn.config(bg=purpleColor)

        elif(cardinality == "NW"):

            msg = "G0 X-" + str(move_resolution) + " Y" + str(move_resolution)

        elif(cardinality == "N"):

            msg = "G0 Y" + str(move_resolution)

        elif(cardinality == "NE"):

            msg = "G0 X" + str(move_resolution) + " Y" + str(move_resolution)

        elif(cardinality == "W"):

            msg = "G0 X-" + str(move_resolution)

        elif(cardinality == "E"):

            msg = "G0 X" + str(move_resolution)

        elif(cardinality == "SW"):

            msg = "G0 X-" + str(move_resolution) + " Y-" + str(move_resolution)

        elif(cardinality == "S"):

            msg = "G0 Y-" + str(move_resolution)

        elif(cardinality == "SE"):

            msg = "G0 X" + str(move_resolution) + " Y-" + str(move_resolution)

    elif(xyab_mode == "ab"):

        if(cardinality == "XY/AB"):

            xyab_mode = "xy"
            xy_buttons["XY/AB"].config(text="XY")
            for btn in xy_buttons.values():
                btn.config(bg=cyanColor)

        elif(cardinality == "NW"):

            msg = "G0 A-" + str(move_resolution) + " B" + str(move_resolution)

        elif(cardinality == "N"):

            msg = "G0 B" + str(move_resolution)

        elif(cardinality == "NE"):

            msg = "G0 A" + str(move_resolution) + " B" + str(move_resolution)

        elif(cardinality == "W"):

            msg = "G0 A-" + str(move_resolution)

        elif(cardinality == "E"):

            msg = "G0 A" + str(move_resolution)

        elif(cardinality == "SW"):

            msg = "G0 A-" + str(move_resolution) + " B-" + str(move_resolution)

        elif(cardinality == "S"):

            msg = "G0 B-" + str(move_resolution)

        elif(cardinality == "SE"):

            msg = "G0 A" + str(move_resolution) + " B-" + str(move_resolution)

    print(msg)

    if(msg is not None):

        send_to_skr(msg)

    send_to_skr("G90")

def delta_toggle_func(distance):

    global move_resolution

    if(distance == 0.1):

        move_resolution = 0.1
        tog01_button['bg'] = greenColor
        tog1_button['bg'] = yellowColor
        tog10_button['bg'] = yellowColor

    elif(distance == 1):

        move_resolution = 1
        tog01_button['bg'] = yellowColor
        tog1_button['bg'] = greenColor
        tog10_button['bg'] = yellowColor
    
    elif(distance == 10):

        move_resolution = 10
        tog01_button['bg'] = yellowColor
        tog1_button['bg'] = yellowColor
        tog10_button['bg'] = greenColor

    print(move_resolution)

def home_func():

    print("Home")

    send_to_tft("Homing all axes...")
    send_to_skr("G28")
    #wait_for_move_completion()
    send_to_skr("M154 S0")

    send_to_skr("G0 X60 Y60 A17.5 B17.5 F360")
    #wait_for_move_completion()

    send_to_tft("Turn on Laser 2 for alignment")
    send_to_laser("LASER 2")  # Turn on Laser 2

    send_to_tft("Move to TOP-RIGHT corner of the sample, then press 'Calibrate'")

    calibrate_button['state'] = 'normal'

def calibrate_func():

    global run_name, um_per_pixel, SMU_bias, calibration_point, w, h, Xoffset, Yoffset

    collect_corner_position()

    run_name = sample_name_entry.get_value()

    try:
        w = float(sample_w_entry.get_value())
        if(w <= 0):
        
            raise ValueError("Width must be > 0")
        
        h = float(sample_l_entry.get_value())
        if(h <= 0):
        
            raise ValueError("Length must be > 0")

        um_per_pixel = float(pixel_res_entry.get_value())
        if(um_per_pixel <= 0):
        
            raise ValueError("um_per_pixel must be > 0")

        SMU_bias = float(bias_entry.get_value())

        if calibration_point:
            Xcal = calibration_point["X"]
            Ycal = calibration_point["Y"]

            # Move XY to sample center
            Xcenter = Xcal + (w / 2)
            Ycenter = Ycal + (h / 2)
            send_to_skr(f"G0 X{Xcenter:.2f} Y{Ycenter:.2f}")
            send_to_tft(f"Sample centered at X{Xcenter:.2f} Y{Ycenter:.2f}")

            Xoffset = LASER_POSITIONS[2]["X"]-Xcenter
            Yoffset = LASER_POSITIONS[2]["Y"]-Ycenter

            print(f"Xoffset: {Xoffset}, Yoffset: {Yoffset}")

            # --- AB Perimeter Check ---

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
                #wait_for_move_completion()
                #time.sleep(1)

            terminal.writeln("If the perimeter is okay, check all the desired lasers to use and press 'Start'. Otherwise, realign the corner and press 'Calibrate' again", tag="out")

        start_button["state"] = 'normal'

        speed = 60.0

        eta = (w/speed)*(h/um_per_pixel)*(1000.0/60.0)

        hours = int(eta)
        minutes = int(round((eta - hours) * 60))
        # Handle cases like 1.999 -> 2:00
        if minutes == 60:
            hours += 1
            minutes = 0

        terminal.writeln(f"Estimate processing time per laser: {hours:02d}hours :{minutes:02d}minutes", tag="out")

        print("Calibrate")

    except:
        terminal.writeln("Values must be numerical.", tag="out")
        
def start_func():

    global selected_lasers, calibration_point, w, h, delta, Xoffset, Yoffset, sweepFlag

    selected_lasers = []

    send_to_laser("LASER 0")

    time.sleep(2)

    if(l1_check_var.get()):
        selected_lasers.extend("1")
    if(l2_check_var.get()):
        selected_lasers.extend("2")
    if(l3_check_var.get()):
        selected_lasers.extend("3")
    if(l4_check_var.get()):
        selected_lasers.extend("4")
    if(l5_check_var.get()):
        selected_lasers.extend("5")
    if(l6_check_var.get()):
        selected_lasers.extend("6")

    send_to_tft(f"Selected Lasers: {selected_lasers}")

    if(selected_lasers):

        #sweep()
        print("sweep")
    else:

        terminal.writeln("Select at least one laser to use to continue", tag="out")

    print("Start")

def torque_func():

    if(torque_button.cget("bg") == redColor):
        torque_button.config(bg = greenColor)
        torque_button.config(text = "Torque enabled")
        send_to_skr("M17")

    elif(torque_button.cget("bg") == greenColor):
        torque_button.config(bg = redColor)
        torque_button.config(text = "Torque disabled")
        send_to_skr("M18")

def load_func():

    print("load")

def new_func():

    print("new")

# Initialize the main application window
root = tk.Tk()
root.geometry(window_size)  # Set the window size
root.title(window_title)  # Set the window title
root.configure(bg=backgndColor)  # Set the background color

# Define coordinates for button placement
leftPanelX = 750
rightPanelX = 980
buttonsYcoord = 500

# Circle diameter
diameter_laser = 20
diameter_status = 10

# Define a custom font for labels and entries
custom_font = tkfont.Font(family="Helvetica", size=10, weight="bold")

# Options for labels and entries
label_options = {
    "font": custom_font,
    "bg": "gray",
    "fg": "black",
    "padx": 5,
    "pady": 5
}

entry_options = {
    "font": custom_font,
    "bg": "lightyellow",
    "fg": "darkblue",
    "bd": 5,  # border width
    "relief": "sunken"  # border style
}

class LabeledEntry(tk.Frame):
    def __init__(self, master, label_text, initial_value="", label_width=20, entry_width=20, label_options=None, entry_options=None, row=0, column=0, on_enter=None, validate_callback=None, **kwargs):
        # Call the constructor of the parent class (tk.Frame) with master and any additional keyword arguments
        super().__init__(master, **kwargs)

        # If no label_options are provided, initialize as an empty dictionary
        label_options = label_options or {}
        # If no entry_options are provided, initialize as an empty dictionary
        entry_options = entry_options or {}

        # Add the width parameter to label_options and entry_options
        label_options['width'] = label_width
        entry_options['width'] = entry_width

        # Create a Label widget with the provided text and options
        self.label = tk.Label(self, text=label_text, **label_options)
        # Position the Label widget using grid layout at the specified row and column, with some padding
        self.label.grid(row=row, column=column, padx=(0, 5))

        # Create an Entry widget with the provided options
        self.entry = tk.Entry(self, **entry_options)
        # Insert the initial value into the Entry widget
        self.entry.insert(0, initial_value)
        # Position the Entry widget using grid layout at the specified row and next column
        self.entry.grid(row=row, column=column + 1)

        # If an on_enter function is provided, bind it to the Return (Enter) key event for the Entry widget
        if on_enter:
            self.entry.bind("<Return>", on_enter)

        # If a validate_callback function is provided, set up validation for the Entry widget
        if validate_callback:
            # 'validate' option is set to 'key', meaning validation occurs on any keystroke
            # 'validatecommand' is set to the validate_callback function registered with Tkinter, which receives the current value as a parameter ("%P")
            self.entry.config(validate="key", validatecommand=(self.register(validate_callback), "%P"))

    # Method to get the current value of the Entry widget
    def get_value(self):
        return self.entry.get()

    # Method to set a new value in the Entry widget
    def set_value(self, new_value):
        self.entry.delete(0, tk.END)  # Remove the current text in the Entry widget
        self.entry.insert(0, new_value)  # Insert the new value into the Entry widget

plot_select_frame = tk.Frame(
    root,
    #width=300,
    #height=200,
    bg=highlightbackColor,            # background color
    bd=5,                      # border width in pixels
    relief="ridge",            # border style: flat, raised, sunken, groove, ridge, solid
)

plot_select_frame.place(x=10, y=10)

plot_select_label = tk.Label(plot_select_frame, text='Show plot for', font=("Arial", 13, "bold"), fg="white", bg=plot_select_frame.cget("bg"))
plot_select_label.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

# Labels arranged in grid order
layout = ["L1", "L2", "L3", "L4", "L5", "L6"]

plot_buttons = {}

for c, label in enumerate(layout):

    # Option A: lambda with default arg to capture the label
    cmd = lambda d=label: plot_select_func(d)

    btn = tk.Button(
        plot_select_frame,
        text=label,
        font=("Arial", 12),
        fg=butTextColor,
        bg=cyanColor,
        borderwidth=2,
        relief="raised",
        width=2,
        height=1,
        command=cmd,
        cursor="hand2",
        state='disabled'
    )
    btn.grid(row=0, column=c+1, padx=5, pady=5, sticky="nsew")
    plot_buttons[label] = btn

canvas_plot = tk.Canvas(
    root,

    # --- Size ---
    width=700,          # width in pixels
    height=700,         # height in pixels

    # --- Colors ---
    bg="white",     # background color
    borderwidth=5,      # thickness of the border
    highlightthickness=3,      # thickness of focus highlight border
    highlightbackground="black", # border color when not focused
    highlightcolor="blue",      # border color when focused

    # --- Scrolling region (for large drawings) ---
    scrollregion=(0, 0, 700, 700),  # virtual area

    # --- Cursor ---
    cursor="cross",     # mouse pointer type (e.g., "arrow", "hand2", "cross")

    # --- Relief (border style) ---
    relief="ridge",     # options: flat, raised, sunken, groove, ridge, solid

    # --- Take focus ---
    takefocus=False,     # whether it can receive focus by tabbing
)
canvas_plot.place(x=10, y=70)

# Create and place the "Connect SMU" button
how_to_button = tk.Button(
    root,
    text="How-to",
    font=("Arial", 12),
    fg=butTextColor,
    bg=yellowColor,
    borderwidth=2,
    relief="raised",
    width=10,
    height=2,
    command=how_to_func,
    cursor="hand2",
    state='normal'
)
how_to_button.place(x=rightPanelX+60, y=20)

# Create and place the "Run" button
init_button = tk.Button(
    root,
    text="Initialise devices",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=15,
    height=2,
    command=init_ports_func,
    cursor="hand2",
    state='normal'
)
init_button.place(x=leftPanelX, y=20)

connection_frame = tk.Frame(
    root,
    #width=300,
    #height=200,
    bg=highlightbackColor,            # background color
    bd=5,                      # border width in pixels
    relief="ridge",            # border style: flat, raised, sunken, groove, ridge, solid
)

connection_frame.place(x=leftPanelX+160, y=20)

canvas_skr = tk.Canvas(connection_frame, width=diameter_status, height=diameter_status, 
                   bg=connection_frame.cget("bg"), highlightthickness=0)
canvas_skr.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)

# Draw a circle filling the canvas
circle_skr = canvas_skr.create_oval(
    0, 0, diameter_status, diameter_status,
    fill="#FF0000", outline=""
)

skr_label = tk.Label(connection_frame, text='SKR', font=("Arial", 9, "bold"), fg="white", bg=connection_frame.cget("bg"))
skr_label.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

canvas_lcd = tk.Canvas(connection_frame, width=diameter_status, height=diameter_status, 
                   bg=connection_frame.cget("bg"), highlightthickness=0)
canvas_lcd.grid(row=0, column=2, sticky="nsew", padx=0, pady=0)

# Draw a circle filling the canvas
circle_lcd = canvas_lcd.create_oval(
    0, 0, diameter_status, diameter_status,
    fill="#FF0000", outline=""
)

lcd_label = tk.Label(connection_frame, text='LCD', font=("Arial", 9, "bold"), fg="white", bg=connection_frame.cget("bg"))
lcd_label.grid(row=0, column=3, sticky="nsew", padx=0, pady=0)

canvas_las = tk.Canvas(connection_frame, width=diameter_status, height=diameter_status, 
                   bg=connection_frame.cget("bg"), highlightthickness=0)
canvas_las.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

# Draw a circle filling the canvas
circle_las = canvas_las.create_oval(
    0, 0, diameter_status, diameter_status,
    fill="#FF0000", outline=""
)

las_label = tk.Label(connection_frame, text='Laser', font=("Arial", 9, "bold"), fg="white", bg=connection_frame.cget("bg"))
las_label.grid(row=1, column=1, sticky="nsew", padx=0, pady=0)

canvas_smu = tk.Canvas(connection_frame, width=diameter_status, height=diameter_status, 
                   bg=connection_frame.cget("bg"), highlightthickness=0)
canvas_smu.grid(row=1, column=2, sticky="nsew", padx=0, pady=0)

# Draw a circle filling the canvas
circle_smu = canvas_smu.create_oval(
    0, 0, diameter_status, diameter_status,
    fill="#FF0000", outline=""
)

smu_label = tk.Label(connection_frame, text='SMU', font=("Arial", 9, "bold"), fg="white", bg=connection_frame.cget("bg"))
smu_label.grid(row=1, column=3, sticky="nsew", padx=0, pady=0)


laser_frame = tk.Frame(
    root,
    #width=300,
    #height=200,
    bg=highlightbackColor,            # background color
    bd=5,                      # border width in pixels
    relief="ridge",            # border style: flat, raised, sunken, groove, ridge, solid
)

laser_frame.place(x=rightPanelX+10, y=100)

laser_select_label = tk.Label(laser_frame, text='Laser Select', font=("Arial", 13, "bold"), fg="white", bg=laser_frame.cget("bg"))
laser_select_label.grid(row=0, column=0,columnspan=4, sticky="nsew", padx=5, pady=5)

# Laser 1

l1_check_var = tk.BooleanVar(value=False)   # starts unchecked

# Create the checkbox and link it to the variable
l1_checkbox = tk.Checkbutton(
    laser_frame,
    text="",
    variable=l1_check_var,
    onvalue=True,   # value when checked
    offvalue=False,  # value when unchecked
)
l1_checkbox.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "L1 On Toggle" button
l1_on_button = tk.Button(
    laser_frame,
    text="L1",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=2,
    height=1,
    command=lambda: laser_toggle("LASER 1"),
    cursor="hand2",
    state='disabled'
)
l1_on_button.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)

canvas_l1 = tk.Canvas(laser_frame, width=diameter_laser, height=diameter_laser, 
                   bg=laser_frame.cget("bg"), highlightthickness=0)
canvas_l1.grid(row=1, column=2, sticky="nsew", padx=5, pady=5)

# Draw a circle filling the canvas
circle_l1 = canvas_l1.create_oval(
    0, 0, diameter_laser, diameter_laser,
    fill="#0000FF", outline=""
)

l1_label = tk.Label(laser_frame, text='444nm', font=("Arial", 13, "bold"), fg="white", bg=laser_frame.cget("bg"))
l1_label.grid(row=1, column=3, sticky="nsew", padx=5, pady=5)


# Laser 2

l2_check_var = tk.BooleanVar(value=False)   # starts unchecked

# Create the checkbox and link it to the variable
l2_checkbox = tk.Checkbutton(
    laser_frame,
    text="",
    variable=l2_check_var,
    onvalue=True,   # value when checked
    offvalue=False,  # value when unchecked
)
l2_checkbox.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "L1 On Toggle" button
l2_on_button = tk.Button(
    laser_frame,
    text="L2",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=2,
    height=1,
    command=lambda: laser_toggle("LASER 2"),
    cursor="hand2",
    state='disabled'
)
l2_on_button.grid(row=2, column=1, sticky="nsew", padx=5, pady=5)

canvas_l2 = tk.Canvas(laser_frame, width=diameter_laser, height=diameter_laser, 
                   bg=laser_frame.cget("bg"), highlightthickness=0)
canvas_l2.grid(row=2, column=2, sticky="nsew", padx=5, pady=5)

# Draw a circle filling the canvas
circle_l2 = canvas_l2.create_oval(
    0, 0, diameter_laser, diameter_laser,
    fill="#00FF00", outline=""
)

l2_label = tk.Label(laser_frame, text='519nm', font=("Arial", 13, "bold"), fg="white", bg=laser_frame.cget("bg"))
l2_label.grid(row=2, column=3, sticky="nsew", padx=5, pady=5)

# Laser 3

l3_check_var = tk.BooleanVar(value=False)   # starts unchecked

# Create the checkbox and link it to the variable
l3_checkbox = tk.Checkbutton(
    laser_frame,
    text="",
    variable=l3_check_var,
    onvalue=True,   # value when checked
    offvalue=False,  # value when unchecked
)
l3_checkbox.grid(row=3, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "L1 On Toggle" button
l3_on_button = tk.Button(
    laser_frame,
    text="L3",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=2,
    height=1,
    command=lambda: laser_toggle("LASER 3"),
    cursor="hand2",
    state='disabled'
)
l3_on_button.grid(row=3, column=1, sticky="nsew", padx=5, pady=5)

canvas_l3 = tk.Canvas(laser_frame, width=diameter_laser, height=diameter_laser, 
                   bg=laser_frame.cget("bg"), highlightthickness=0)
canvas_l3.grid(row=3, column=2, sticky="nsew", padx=5, pady=5)

# Draw a circle filling the canvas
circle_l3 = canvas_l3.create_oval(
    0, 0, diameter_laser, diameter_laser,
    fill="#FF0000", outline=""
)

l3_label = tk.Label(laser_frame, text='652nm', font=("Arial", 13, "bold"), fg="white", bg=laser_frame.cget("bg"))
l3_label.grid(row=3, column=3, sticky="nsew", padx=5, pady=5)

# Laser 4

l4_check_var = tk.BooleanVar(value=False)   # starts unchecked

# Create the checkbox and link it to the variable
l4_checkbox = tk.Checkbutton(
    laser_frame,
    text="",
    variable=l4_check_var,
    onvalue=True,   # value when checked
    offvalue=False,  # value when unchecked
)
l4_checkbox.grid(row=4, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "L1 On Toggle" button
l4_on_button = tk.Button(
    laser_frame,
    text="L4",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=2,
    height=1,
    command=lambda: laser_toggle("LASER 4"),
    cursor="hand2",
    state='disabled'
)
l4_on_button.grid(row=4, column=1, sticky="nsew", padx=5, pady=5)

canvas_l4 = tk.Canvas(laser_frame, width=diameter_laser, height=diameter_laser, 
                   bg=laser_frame.cget("bg"), highlightthickness=0)
canvas_l4.grid(row=4, column=2, sticky="nsew", padx=5, pady=5)

# Draw a circle filling the canvas
circle_l4 = canvas_l4.create_oval(
    0, 0, diameter_laser, diameter_laser,
    fill="#D00000", outline=""
)

l4_label = tk.Label(laser_frame, text='676nm', font=("Arial", 13, "bold"), fg="white", bg=laser_frame.cget("bg"))
l4_label.grid(row=4, column=3, sticky="nsew", padx=5, pady=5)

# Laser 5

l5_check_var = tk.BooleanVar(value=False)   # starts unchecked

# Create the checkbox and link it to the variable
l5_checkbox = tk.Checkbutton(
    laser_frame,
    text="",
    variable=l5_check_var,
    onvalue=True,   # value when checked
    offvalue=False,  # value when unchecked
)
l5_checkbox.grid(row=5, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "L1 On Toggle" button
l5_on_button = tk.Button(
    laser_frame,
    text="L5",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=2,
    height=1,
    command=lambda: laser_toggle("LASER 5"),
    cursor="hand2",
    state='disabled'
)
l5_on_button.grid(row=5, column=1, sticky="nsew", padx=5, pady=5)

canvas_l5 = tk.Canvas(laser_frame, width=diameter_laser, height=diameter_laser, 
                   bg=laser_frame.cget("bg"), highlightthickness=0)
canvas_l5.grid(row=5, column=2, sticky="nsew", padx=5, pady=5)

# Draw a circle filling the canvas
circle_l5 = canvas_l5.create_oval(
    0, 0, diameter_laser, diameter_laser,
    fill="#600000", outline=""
)

l5_label = tk.Label(laser_frame, text='785nm', font=("Arial", 13, "bold"), fg="white", bg=laser_frame.cget("bg"))
l5_label.grid(row=5, column=3, sticky="nsew", padx=5, pady=5)

# Laser 6

l6_check_var = tk.BooleanVar(value=False)   # starts unchecked

# Create the checkbox and link it to the variable
l6_checkbox = tk.Checkbutton(
    laser_frame,
    text="",
    variable=l6_check_var,
    onvalue=True,   # value when checked
    offvalue=False,  # value when unchecked
)
l6_checkbox.grid(row=6, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "L1 On Toggle" button
l6_on_button = tk.Button(
    laser_frame,
    text="L6",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=2,
    height=1,
    command=lambda: laser_toggle("LASER 6"),
    cursor="hand2",
    state='disabled'
)
l6_on_button.grid(row=6, column=1, sticky="nsew", padx=5, pady=5)

canvas_l6 = tk.Canvas(laser_frame, width=diameter_laser, height=diameter_laser, 
                   bg=laser_frame.cget("bg"), highlightthickness=0)
canvas_l6.grid(row=6, column=2, sticky="nsew", padx=5, pady=5)

# Draw a circle filling the canvas
circle_l6 = canvas_l6.create_oval(
    0, 0, diameter_laser, diameter_laser,
    fill="#000000", outline=""
)

l6_label = tk.Label(laser_frame, text='848nm', font=("Arial", 13, "bold"), fg="white", bg=laser_frame.cget("bg"))
l6_label.grid(row=6, column=3, sticky="nsew", padx=5, pady=5)

sample_frame = tk.Frame(
    root,
    #width=300,
    #height=200,
    bg=highlightbackColor,            # background color
    bd=5,                      # border width in pixels
    relief="ridge",            # border style: flat, raised, sunken, groove, ridge, solid
)

sample_frame.place(x=leftPanelX, y=100)

sample_name_entry = LabeledEntry(sample_frame, "Run Name: ", initial_value="--Name", label_options=label_options, entry_options=entry_options, label_width= 10, entry_width= 14)
sample_name_entry.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

sample_size_label = tk.Label(sample_frame, text='Sample Size', font=("Arial", 13, "bold"), fg="white", bg=sample_frame.cget("bg"))
sample_size_label.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

sample_w_entry = LabeledEntry(sample_frame, "Width (x, mm): ", initial_value="10.0", label_options=label_options, entry_options=entry_options, label_width= 10, entry_width= 14)
sample_w_entry.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)

sample_l_entry = LabeledEntry(sample_frame, "Length (y, mm): ", initial_value="10.0", label_options=label_options, entry_options=entry_options, label_width= 10, entry_width= 14)
sample_l_entry.grid(row=3, column=0, sticky="nsew", padx=5, pady=5)

pixel_res_label = tk.Label(sample_frame, text='Pixel resolution', font=("Arial", 13, "bold"), fg="white", bg=sample_frame.cget("bg"))
pixel_res_label.grid(row=4, column=0, sticky="nsew", padx=5, pady=5)

pixel_res_entry = LabeledEntry(sample_frame, "um/pixel:", initial_value="1000", label_options=label_options, entry_options=entry_options, label_width= 10, entry_width= 14)
pixel_res_entry.grid(row=5, column=0, sticky="nsew", padx=5, pady=5)

bias_entry = LabeledEntry(sample_frame, "SMU Bias (Def: 0.0V): ", initial_value="0.0", label_options=label_options, entry_options=entry_options, label_width= 16, entry_width= 8)
bias_entry.grid(row=6, column=0, sticky="nsew", padx=5, pady=5)

xy_frame = tk.Frame(
    root,
    #width=300,
    #height=200,
    bg=highlightbackColor,            # background color
    bd=5,                      # border width in pixels
    relief="ridge",            # border style: flat, raised, sunken, groove, ridge, solid
)

xy_frame.place(x=leftPanelX+15, y=400)

xy_label = tk.Label(xy_frame, text='Stage movement', font=("Arial", 13, "bold"), fg="white", bg=xy_frame.cget("bg"))
xy_label.grid(row=0, column=0,columnspan=3, sticky="nsew", padx=5, pady=5)

# Labels arranged in grid order
layout = [
    ["NW", "N",  "NE"],
    ["W",  "XY/AB",  "E" ],
    ["SW", "S",  "SE"],
]

# dictionary to hold references
xy_buttons = {}

for r, row in enumerate(layout):
    for c, label in enumerate(row):

        # Option A: lambda with default arg to capture the label
        cmd = lambda d=label: xy_func(d)

        btn = tk.Button(
            xy_frame,
            text=label,
            font=("Arial", 12),
            fg=butTextColor,
            bg=cyanColor,
            borderwidth=2,
            relief="raised",
            width=5,
            height=2,
            command=cmd,
            cursor="hand2",
            state='disabled'
        )
        btn.grid(row=r+1, column=c, padx=5, pady=5, sticky="nsew")
        xy_buttons[label] = btn

# (optional) make the grid expand nicely
# for i in range(3):
#     xy_frame.grid_rowconfigure(i, weight=1)
#     xy_frame.grid_columnconfigure(i, weight=1)

# Create and place the "10mm Toggle" button
tog10_button = tk.Button(
    xy_frame,
    text="10mm",
    font=("Arial", 12),
    fg=butTextColor,
    bg=yellowColor,
    borderwidth=2,
    relief="raised",
    width=4,
    height=2,
    command=lambda: delta_toggle_func(10),
    cursor="hand2",
    state='disabled'
)
tog10_button.grid(row=5, column=0, sticky="nsew", padx=5, pady=25)

# Create and place the "1mm Toggle" button
tog1_button = tk.Button(
    xy_frame,
    text="1mm",
    font=("Arial", 12),
    fg=butTextColor,
    bg=greenColor,
    borderwidth=2,
    relief="raised",
    width=4,
    height=2,
    command=lambda: delta_toggle_func(1),
    cursor="hand2",
    state='disabled'
)
tog1_button.grid(row=5, column=1, sticky="nsew", padx=5, pady=25)

# Create and place the "0.1mm Toggle" button
tog01_button = tk.Button(
    xy_frame,
    text="0.1mm",
    font=("Arial", 12),
    fg=butTextColor,
    bg=yellowColor,
    borderwidth=2,
    relief="raised",
    width=4,
    height=2,
    command=lambda: delta_toggle_func(0.1),
    cursor="hand2",
    state='disabled'
)
tog01_button.grid(row=5, column=2, sticky="nsew", padx=5, pady=25)

motors_frame = tk.Frame(
    root,
    #width=300,
    #height=200,
    bg=highlightbackColor,            # background color
    bd=5,                      # border width in pixels
    relief="ridge",            # border style: flat, raised, sunken, groove, ridge, solid
)

motors_frame.place(x=rightPanelX+20, y=425)

# Create and place the "Home axis" button
home_button = tk.Button(
    motors_frame,
    text="Home axis",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=15,
    height=2,
    command=home_func,
    cursor="hand2",
    state='disabled'
)
home_button.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "Calibrate corner" button
calibrate_button = tk.Button(
    motors_frame,
    text="Calibrate corner",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=15,
    height=2,
    command=calibrate_func,
    cursor="hand2",
    state='disabled'
)
calibrate_button.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "Start" button
start_button = tk.Button(
    motors_frame,
    text="START",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=15,
    height=2,
    command=start_func,
    cursor="hand2",
    state='disabled'
)
start_button.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "Disable torque" button
torque_button = tk.Button(
    motors_frame,
    text="Torque enabled",
    font=("Arial", 12),
    fg=butTextColor,
    bg=greenColor,
    borderwidth=2,
    relief="raised",
    width=15,
    height=2,
    command=torque_func,
    cursor="hand2",
    state='disabled'
)
torque_button.grid(row=3, column=0, sticky="nsew", padx=5, pady=5)

file_frame = tk.Frame(
    root,
    #width=300,
    #height=200,
    bg=highlightbackColor,            # background color
    bd=5,                      # border width in pixels
    relief="ridge",            # border style: flat, raised, sunken, groove, ridge, solid
)

file_frame.place(x=leftPanelX+35, y=750)

# Create and place the "Save result" button
save_button = tk.Button(
    file_frame,
    text="Save result",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=18,
    height=2,
    command=save_func,
    cursor="hand2",
    state='disabled'
)
save_button.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "Load result" button
load_button = tk.Button(
    file_frame,
    text="Load result",
    font=("Arial", 12),
    fg=butTextColor,
    bg=yellowColor,
    borderwidth=2,
    relief="raised",
    width=18,
    height=2,
    command=load_func,
    cursor="hand2",
    state='normal'
)
load_button.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

# Create and place the "CLEAR DATA" button
clear_button = tk.Button(
    file_frame,
    text="CLEAR DATA",
    font=("Arial", 12),
    fg=butTextColor,
    bg=blueColor,
    borderwidth=2,
    relief="raised",
    width=18,
    height=2,
    command=clear_func,
    cursor="hand2",
    state='disabled'
)
clear_button.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

# Create and place the "New Run" button
new_button = tk.Button(
    file_frame,
    text="New Run",
    font=("Arial", 12),
    fg=butTextColor,
    bg=redColor,
    borderwidth=2,
    relief="raised",
    width=18,
    height=2,
    command=new_func,
    cursor="hand2",
    state='disabled'
)
new_button.grid(row=1, column=1, sticky="nsew", padx=5, pady=5)

class TerminalPane(ttk.Frame):
    def __init__(
        self, master, *,
        on_command=None,           # callback: def on_command(cmd_str): ...
        history_capacity=100,
        font=("Consolas", 11),
        bg="#111", fg="#EEE",
        prompt="> ",
        **kwargs
    ):
        super().__init__(master, **kwargs)

        self.on_command = on_command
        self.history = deque(maxlen=history_capacity)
        self.history_index = None
        self.prompt = prompt

        # ----- Output area (Text + Scrollbar)
        self.output = tk.Text(
            self,
            wrap="word",
            undo=False,
            font=font,
            bg=bg, fg=fg,
            insertbackground=fg,   # caret color
            relief="flat",
            height=4
        )
        self.output.config(state="disabled")
        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=yscroll.set)

        # ----- Input line
        self.input_var = tk.StringVar()
        self.input = tk.Entry(self, textvariable=self.input_var, font=font, relief="flat", bg=bg, fg=fg, insertbackground=fg)
        # ttk.Entry doesn't easily allow fg/bg, so use tk.Entry for theming consistency

        # Layout
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.output.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.input.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # Tags for styling output lines if you want
        self.output.tag_configure("in", foreground="#9CDCFE")    # user input echo
        self.output.tag_configure("out", foreground="#C8C8C8")   # device output
        self.output.tag_configure("err", foreground="#F44747")   # errors

        # Key bindings
        self.input.bind("<Return>", self._on_return)
        self.input.bind("<Up>", self._history_prev)
        self.input.bind("<Down>", self._history_next)
        self.input.bind("<Control-l>", self._clear)   # Ctrl+L to clear
        self.input.bind("<Escape>", self._clear_line) # Esc clears input
        # Optional: Ctrl+U delete to start-of-line
        self.input.bind("<Control-u>", self._kill_line)

        # Initial prompt line in output
        self.writeln("Terminal ready.", tag="out")
        self._focus_input()

    # ---------- Public API ----------
    def write(self, text, tag="out"):
        """Append text (no newline) to the terminal output."""
        self._append(text, tag)

    def writeln(self, text="", tag="out"):
        """Append text with newline to the terminal output."""
        self._append(text + "\n", tag)

    def set_prompt(self, prompt):
        self.prompt = prompt

    def focus_input(self):
        self._focus_input()

    # Thread-safe helper for writers in other threads
    def write_threadsafe(self, text, tag="out"):
        self.after(0, lambda: self.write(text, tag))

    def writeln_threadsafe(self, text="", tag="out"):
        self.after(0, lambda: self.writeln(text, tag))

    # ---------- Internals ----------
    def _append(self, text, tag):
        self.output.config(state="normal")
        if tag:
            self.output.insert("end", text, tag)
        else:
            self.output.insert("end", text)
        self.output.see("end")
        self.output.config(state="disabled")

    def _on_return(self, event):
        cmd = self.input_var.get()
        if cmd.strip():
            # Echo what the user typed (like PuTTY)
            self.writeln(self.prompt + cmd, tag="in")
            # Store in history
            self.history.append(cmd)
        self.history_index = None
        self.input_var.set("")
        # Hand off to your processor
        if self.on_command:
            try:
                self.on_command(cmd)
            except Exception as e:
                self.writeln(f"[handler error] {e}", tag="err")
        return "break"  # prevent default beep

    def _history_prev(self, event):
        if not self.history:
            return "break"
        if self.history_index is None:
            self.history_index = len(self.history) - 1
        else:
            self.history_index = max(0, self.history_index - 1)
        self.input_var.set(self.history[self.history_index])
        self.input.icursor("end")
        return "break"

    def _history_next(self, event):
        if self.history_index is None:
            return "break"
        if self.history_index >= len(self.history) - 1:
            self.history_index = None
            self.input_var.set("")
        else:
            self.history_index += 1
            self.input_var.set(self.history[self.history_index])
            self.input.icursor("end")
        return "break"

    def _clear(self, event=None):
        self.output.config(state="normal")
        self.output.delete("1.0", "end")
        self.output.config(state="disabled")
        self.writeln("Cleared.", tag="out")
        return "break"

    def _clear_line(self, event=None):
        self.input_var.set("")
        return "break"

    def _kill_line(self, event=None):
        # Ctrl+U: delete from start to cursor
        pos = self.input.index("insert")
        self.input_var.set(self.input_var.get()[pos:])
        self.input.icursor(0)
        return "break"

    def _focus_input(self):
        self.input.focus_set()

# Example "device output" simulator
def fake_device_writer(term: TerminalPane):
    # Simulate messages coming in asynchronously
    import time
    msgs = ["Device: Hello.", "Device: Status OK.", "Device: Ready.", "Initialise devices to start the program"]
    for m in msgs:
        time.sleep(0.8)
        term.writeln_threadsafe(m, tag="out")

def handle_command(cmd):
    # Here you'd send cmd to your serial handler.
    # We just echo a fake response:
    terminal.writeln(f"echo: {cmd}", tag="out")
    
    if(cmd == "debug"):

        terminal.writeln("Entering debug mode, enabling all buttons", tag="out")

        home_button["state"] = 'normal'
        calibrate_button["state"] = 'normal'
        start_button["state"] = 'normal'

        save_button["state"] = 'normal'
        clear_button["state"] = 'normal'
        new_button["state"] = 'normal'

        l1_on_button['state'] = 'normal'
        l2_on_button['state'] = 'normal'
        l3_on_button['state'] = 'normal'
        l4_on_button['state'] = 'normal'
        l5_on_button['state'] = 'normal'
        l6_on_button['state'] = 'normal'

        for btn in xy_buttons.values():
                btn.config(state='normal')

        for btn in plot_buttons.values():
                btn.config(state='normal')

        tog01_button['state'] = 'normal'
        tog1_button['state'] = 'normal'
        tog10_button['state'] = 'normal'
        torque_button['state'] = 'normal'

    if(cmd.startswith("LASER")):

        send_to_laser(cmd)

    elif(cmd.startswith("G") or cmd.startswith("M")):

        send_to_skr(cmd)

terminal = TerminalPane(
    root,
    on_command=handle_command,
    prompt="> ",
    #padding=10
)
terminal.place(x=10, y=890, width=1150, height=110)

# Start a dummy background writer
threading.Thread(target=fake_device_writer, args=(terminal,), daemon=True).start()

class ProgressPane(ttk.Frame):
    """
    Determinate progress bar with percent + ETA and easy color styling.

    Style params:
        bg, fg, bar_color, thickness, theme

    API:
        set(value) / step(amount) / reset() / start() / stop()
        set_maximum(maxv)
        set_caption(text)
        set_format(fn)       -> custom percent formatter
        set_eta_enabled(on)  -> show/hide ETA
    """
    def __init__(
        self, master, *,
        maximum=100,
        value=0,
        length=300,
        orient="horizontal",

        # styling
        bg="#2b2b2b",
        fg="#ffffff",
        bar_color="#4caf50",
        thickness=14,
        theme="clam",

        show_percent=True,
        show_eta=True,
        caption=None,
        font=("Segoe UI", 10),
        percent_font=("Consolas", 11),
        **kwargs
    ):
        super().__init__(master, **kwargs)

        # --- State / ETA ---
        self._maximum = float(maximum)
        self._value = float(value)
        self._format = lambda v, m: f"{int(round((v/m)*100))}%" if m else "0%"
        self._eta_enabled = bool(show_eta)
        self._t0 = None                  # start time
        self._last_v = float(value)
        self._ema_rate = None            # exponential moving avg of rate (units/sec)
        self._ema_alpha = 0.2            # smoothing factor
        self._warmup_seconds = 1.2       # suppress noisy early ETAs

        # --- Styles ---
        self._style = ttk.Style(self)
        try: self._style.theme_use(theme)
        except tk.TclError: pass

        uid = hex(id(self))[-6:]
        self._pb_style  = f"PP{uid}.Horizontal.TProgressbar"
        self._lbl_style = f"PP{uid}.TLabel"
        self._frm_style = f"PP{uid}.TFrame"

        self._style.configure(self._frm_style, background=bg)
        self.configure(style=self._frm_style)

        self._style.configure(
            self._pb_style,
            background=bar_color, troughcolor=bg,
            bordercolor=bg, lightcolor=bar_color, darkcolor=bar_color,
            thickness=thickness
        )
        self._style.configure(self._lbl_style, background=bg, foreground=fg, font=percent_font)

        # --- Layout ---
        self.columnconfigure(0, weight=1)

        self._caption_var = tk.StringVar(value=caption or "")
        self._caption_lbl = None
        if caption is not None:
            self._caption_lbl = ttk.Label(self, textvariable=self._caption_var, style=self._lbl_style, font=font)
            self._caption_lbl.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

        self._pb = ttk.Progressbar(
            self, orient=orient, mode="determinate",
            length=length, maximum=self._maximum, style=self._pb_style
        )
        self._pb.grid(row=1, column=0, sticky="ew")

        self._pct_var = tk.StringVar()
        self._pct_lbl = ttk.Label(self, textvariable=self._pct_var, style=self._lbl_style) if show_percent else None
        if self._pct_lbl: self._pct_lbl.grid(row=1, column=1, padx=(8, 0), sticky="e")

        self._eta_var = tk.StringVar()
        self._eta_lbl = ttk.Label(self, textvariable=self._eta_var, style=self._lbl_style) if show_eta else None
        if self._eta_lbl: self._eta_lbl.grid(row=1, column=2, padx=(8, 0), sticky="e")

        self.set(self._value)  # also seeds % and ETA

    # ---- Public API ----
    def set(self, value: float):
        value = max(0.0, min(float(value), self._maximum))
        now = time.monotonic()

        # start clock on first move from zero
        if self._t0 is None and value > 0:
            self._t0 = now
            self._last_v = 0.0
            self._ema_rate = None

        # update rate estimate when progress increases
        if self._t0 is not None and value > self._last_v:
            dt = max(1e-6, now - (getattr(self, "_last_t", now)))
            inst_rate = (value - self._last_v) / dt  # units per second
            self._ema_rate = inst_rate if self._ema_rate is None else (
                self._ema_alpha * inst_rate + (1 - self._ema_alpha) * self._ema_rate
            )
            self._last_v = value
            self._last_t = now

        self._value = value
        self._pb["value"] = self._value
        self._update_percent()
        self._update_eta()
        self.update_idletasks()

    def step(self, amount: float = 1.0):
        self.set(self._value + amount)

    def reset(self):
        self._value = 0.0
        self._pb["value"] = 0.0
        self._t0 = None
        self._last_v = 0.0
        self._ema_rate = None
        self._eta_var.set("ETA: —") if self._eta_lbl else None
        self._update_percent()
        self.update_idletasks()

    def start(self):
        """Alias for reset (begin a new timing window)."""
        self.reset()

    def stop(self):
        self.set(self._maximum)

    def set_maximum(self, maxv: float):
        maxv = max(float(maxv), 1.0)
        ratio = (self._value / self._maximum) if self._maximum else 0
        self._maximum = maxv
        self._pb.configure(maximum=self._maximum)
        self.set(ratio * self._maximum)

    def set_caption(self, text: str | None):
        if text is None:
            if self._caption_lbl: self._caption_lbl.grid_remove()
            return
        if not self._caption_lbl:
            self._caption_lbl = ttk.Label(self, textvariable=self._caption_var, style=self._lbl_style)
            self._caption_lbl.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self._caption_var.set(text)

    def set_format(self, formatter):
        """formatter(value, maximum) -> string"""
        self._format = formatter or (lambda v, m: f"{int(round((v/m)*100))}%" if m else "0%")
        self._update_percent()

    def set_eta_enabled(self, on: bool = True):
        self._eta_enabled = bool(on)
        if self._eta_lbl:
            if on:   self._eta_lbl.grid()
            else:    self._eta_lbl.grid_remove()
        self._update_eta()

    # ---- Internals ----
    def _fmt_eta(self, seconds):
        seconds = int(max(0, round(seconds)))
        h, r = divmod(seconds, 3600)
        m, s = divmod(r, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

    def _update_percent(self):
        if self._pct_lbl:
            self._pct_var.set(self._format(self._value, self._maximum))

    def _update_eta(self):
        if not (self._eta_lbl and self._eta_enabled):
            return
        # No ETA until we have a start and non-zero smoothed rate
        if self._t0 is None:
            self._eta_var.set("ETA: —")
            return
        elapsed = time.monotonic() - self._t0
        if elapsed < self._warmup_seconds or self._ema_rate is None or self._ema_rate <= 1e-9:
            self._eta_var.set("ETA: estimating…")
            return
        remaining_units = max(0.0, self._maximum - self._value)
        eta_sec = remaining_units / self._ema_rate
        self._eta_var.set(f"ETA: {self._fmt_eta(eta_sec)}")

    
pane = ProgressPane(
        root,
        maximum=100,
        value=30,
        caption="Processing…",
        bg=root.cget("bg"),
        fg="white",
        bar_color="cyan",
        thickness=16,
        length=420,
    )

pane.place(x=10, y=800, width=750, height=50)


 # Controls
# btns = ttk.Frame(root)
# btns.pack(padx=16, pady=8, fill="x")
# ttk.Button(btns, text="Start/Reset", command=pane.start).pack(side="left", padx=4)
# ttk.Button(btns, text="Step +7", command=lambda: pane.step(7)).pack(side="left", padx=4)
# ttk.Button(btns, text="Complete", command=pane.stop).pack(side="left", padx=4)
# ttk.Button(btns, text="Set maximum=42", command=lambda: pane.set_maximum(42)).pack(side="left", padx=4)

# Simulate work
def tick(i=0):
    if i > 120:
        return
    pane.step(1)
    root.after(120, lambda: tick(i+1))  # ~1 unit every 120 ms
pane.start()
tick()


# Start the main event loop
root.mainloop()
