"""Draws the laser board's four schematic sheets as SVG."""
import sys
from pathlib import Path

from schlib import NOTE, Sch

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)


def conn_r(s, x, y, ref, desc, pins, w=90, pitch=40):
    """A connector with its pins on the right edge."""
    h = pitch * len(pins)
    s.rect(x, y, w, h)
    pts = []
    for i, (num, name) in enumerate(pins):
        py = y + pitch // 2 + i * pitch
        s.line((x + w, py), (x + w + 20, py))
        s.text(x + w + 9, py - 4, str(num), size=9, color=NOTE,
               anchor="middle")
        s.text(x + w - 6, py + 4, name, size=11, anchor="end")
        pts.append((x + w + 20, py))
    s.text(x, y - 20, ref, bold=True)
    s.text(x, y - 6, desc, size=11)
    return pts


# ====================================================== sheet 1: power
def sheet_power():
    s = Sch(1240, 860, "Laser board, sheet 1 of 4: supply, enable and lid",
            "Draft for drawing in Fusion. Blue names are nets: the same "
            "name on any sheet is the same net.")

    # --- 5 V in
    conn_r(s, 60, 130, "J10", "5 V in, from the SKR (3-pin)",
           [(1, "+5 V"), (2, "unused"), (3, "GND")])
    s.nc(170, 190)
    s.line((170, 230), (190, 230), (190, 240))
    s.gnd(190, 240)
    s.line((170, 150), (230, 150))
    s.netname(200, 142, "+5V_IN")
    s.fuse_h(230, 150, "F1", "polyfuse 0.3 A")
    s.line((290, 150), (860, 150))
    s.pwr(400, 150, "+5V_L")
    s.dot(400, 150)
    for x in (340, 460, 600, 800, 840):
        s.dot(x, 150)
    s.cap_v(340, 150, "C1", "330µ 10 V", polar=True)
    s.gnd(340, 210)
    s.cap_v(460, 150, "C2", "10µ")
    s.gnd(460, 210)
    s.tp(530, 150, "TP1")

    # --- rail readback
    s.res_v(600, 150, "R1", "1M 0.1%", side="l")
    s.dot(600, 210)
    s.res_v(600, 210, "R2", "1M 0.1%", side="l")
    s.gnd(600, 270)
    s.line((600, 210), (700, 210))
    s.dot(650, 210)
    s.cap_v(650, 210, "C6", "100n")
    s.gnd(650, 270)
    s.label(700, 210, "ADC_RAIL")
    s.text(712, 230, "GPIO17", size=10, color=NOTE)

    # --- LDO
    s.cap_v(800, 150, "C3", "1µ", side="l")
    s.gnd(800, 210)
    s.ic(880, 132, 120, "U1", "LP5907MFX-3.3 (SOT-23-5)",
         [(1, "IN", None), (3, "EN", None)],
         [(5, "OUT", None), (4, "NC", "nc")])
    s.line((860, 174), (840, 174), (840, 150))
    s.line((940, 192), (940, 215))
    s.text(944, 207, "2", size=9, color=NOTE)
    s.text(940, 187, "GND", size=11, anchor="middle")
    s.gnd(940, 215)
    s.line((1020, 150), (1180, 150))
    for x in (1060, 1120):
        s.dot(x, 150)
    s.cap_v(1060, 150, "C4", "1µ")
    s.gnd(1060, 210)
    s.cap_v(1120, 150, "C5", "10µ")
    s.gnd(1120, 210)
    s.pwr(1090, 150, "+3V3_A")
    s.dot(1090, 150)
    s.tp(1180, 150, "TP2")

    # --- enable
    s.text(60, 330, "Enable (one line for all six channels) and lid "
           "interlock", bold=True, size=13)
    s.pwr(420, 380, "+3V3_A")
    s.res_v(420, 380, "R7", "10k")
    s.dot(420, 440)
    s.line((420, 440), (540, 440))
    s.tp(480, 440, "TP5")
    s.label(540, 440, "LASER_OFF")
    s.text(552, 460, "high = every set point clamped to zero", size=10,
           color=NOTE)
    s.text(552, 474, "to the gates of Q101 ... Q601", size=10, color=NOTE)
    s.line((420, 440), (420, 460))
    s.nmos(380, 490, "Q1", "BSS138")
    s.line((380, 490), (330, 490))
    s.dot(340, 490)
    s.res_v(340, 490, "R9", "100k", side="r")
    s.gnd(340, 550)
    s.res_h(270, 490, "R8", "1k")
    s.label(270, 490, "EN", side="l")
    s.text(258, 510, "GPIO21", size=10, color=NOTE, anchor="end")
    s.text(258, 524, "high = lasers enabled", size=10, color=NOTE,
           anchor="end")
    # source = LID
    s.line((420, 520), (420, 620))
    s.dot(420, 620)
    s.line((300, 620), (640, 620))
    s.netname(470, 612, "LID")
    s.pwr(540, 560, "+3V3_A")
    s.res_v(540, 560, "R12", "100k")
    s.dot(540, 620)
    s.res_h(240, 620, "R13", "1k")
    s.label(240, 620, "LID_SNS", side="l")
    s.text(228, 640, "GPIO39", size=10, color=NOTE, anchor="end")
    s.text(228, 654, "low = lid shut", size=10, color=NOTE, anchor="end")
    s.conn(660, 600, "J11", "lid switch, closed = lid shut",
           [(1, "LID"), (2, "GND")])
    s.line((640, 660), (620, 660), (620, 670))
    s.gnd(620, 670)
    s.dot(600, 620)
    s.line((600, 620), (600, 770), (640, 770))
    s.conn(660, 750, "JP1", "bypass: 2-pin header, jumper = no interlock",
           [(1, "LID"), (2, "GND")])
    s.line((640, 810), (620, 810), (620, 818))
    s.gnd(620, 818)

    # --- spare amplifiers
    s.text(880, 330, "Spare amplifiers, tied off", bold=True, size=13)
    s.pwr(900, 380, "+3V3_A")
    s.res_v(900, 380, "R10", "100k", side="l")
    s.dot(900, 440)
    s.res_v(900, 440, "R11", "100k", side="l")
    s.gnd(900, 500)
    s.line((900, 440), (950, 440))
    s.dot(950, 440)
    s.netname(925, 432, "VMID")
    for y0, ref in ((400, "U2D"), (560, "U3D")):
        s.opamp(1000, y0, ref, pins=("12", "13", "14"))
        s.line((950, 440), (950, y0), (1000, y0))
        s.line((1080, y0 + 20), (1100, y0 + 20), (1100, y0 + 76),
               (980, y0 + 76), (980, y0 + 40), (1000, y0 + 40))
    s.note(60, 740, [
        "TP3, TP4: ground loops for a scope or meter clip.",
        "R8 + Q1: the ESP32 can only pull LASER_OFF low through Q1 and the",
        "closed lid switch. Unpowered or in reset, Q1 is off and R7 holds",
        "every laser off.",
    ], size=11)
    s.save(OUT / "laser-board-1-supply.svg")


# ==================================================== sheet 2: channel
def sheet_channel():
    s = Sch(1240, 800, "Laser board, sheet 2 of 4: a channel (× 6)",
            "Channel 1 shown. Channel n uses Rn01-Rn09, Cn01-Cn05, Qn01, "
            "Qn02, Dn01, Jn01, TPn1, TPn2 and the pins in the table.")

    # --- set point
    s.label(100, 330, "DAC1", side="l")
    s.line((100, 330), (110, 330))
    s.res_h(110, 330, "R101", "40.2k 0.1%")
    s.line((170, 330), (500, 330))
    for x in (240, 320, 400):
        s.dot(x, 330)
    s.netname(455, 322, "SET1")
    # clamp
    s.nmos(200, 390, "Q101", "BSS138")
    s.line((240, 330), (240, 360))
    s.gnd(240, 420)
    s.line((200, 390), (180, 390))
    s.label(180, 390, "LASER_OFF", side="l")
    s.res_v(320, 330, "R102", "10k 0.1%")
    s.gnd(320, 390)
    s.cap_v(400, 330, "C101", "10n C0G")
    s.gnd(400, 390)

    # --- op-amp and loop
    s.opamp(500, 330, "U2A (MCP6V34)", pins=("3", "2", "1"))
    s.line((580, 350), (610, 350))
    s.dot(600, 350)
    s.res_h(610, 350, "R103", "220R")
    s.line((670, 350), (750, 350))
    s.dot(700, 350)
    s.res_v(700, 350, "R104", "100k", side="l")
    s.gnd(700, 410)
    s.nmos(750, 350, "Q102", "PMV30UN2")
    # source, sense
    s.line((790, 380), (790, 480))
    s.dot(790, 460)
    s.res_v(790, 480, "R105", "10R 0.1%")
    s.gnd(790, 540)
    s.netname(800, 476, "SNS1", anchor="start")
    # feedback
    s.line((790, 460), (680, 460))
    s.res_h(620, 460, "R106", "1k")
    s.line((620, 460), (480, 460), (480, 370), (500, 370))
    s.dot(480, 420)
    s.line((480, 420), (520, 420))
    s.cap_h(520, 420, "C102", "10n C0G")
    s.line((560, 420), (600, 420), (600, 350))
    # current readback
    s.line((790, 460), (860, 460))
    s.tp(835, 460, "TP11")
    s.res_h(860, 460, "R107", "10k")
    s.line((920, 460), (1040, 460))
    s.dot(970, 460)
    s.cap_v(970, 460, "C103", "100n")
    s.gnd(970, 520)
    s.label(1040, 460, "ADC_I1")
    s.text(1052, 480, "0-0.5 V", size=10, color=NOTE)

    # --- drain, module, connector
    s.line((790, 320), (790, 250))
    s.dot(790, 290)
    s.dot(790, 250)
    s.line((690, 250), (850, 250))
    s.line((640, 130), (850, 130))
    s.pwr(640, 130, "+5V_L")
    for x in (690, 750):
        s.dot(x, 130)
        s.dot(x, 250)
    s.diode_v(690, 130, "D101", "BAT54")
    s.cap_v(750, 130, "C105", "100n", dnp=True, length=120)
    s.text(767, 216, "not fitted", size=10, color="#b3261e")
    s.netname(818, 244, "DRN1")
    s.conn(870, 150, "J101", "JST XH 2-pin, to laser 1",
           [(1, "laser +"), (2, "laser −")], w=90)
    s.line((850, 130), (850, 170))
    s.line((850, 210), (850, 250))
    # drain readback
    s.line((790, 290), (860, 290))
    s.tp(830, 290, "TP12")
    s.res_h(860, 290, "R108", "1M 0.1%")
    s.line((920, 290), (1100, 290))
    s.dot(960, 290)
    s.res_v(960, 290, "R109", "1M 0.1%")
    s.gnd(960, 350)
    s.dot(1040, 290)
    s.cap_v(1040, 290, "C104", "100n")
    s.gnd(1040, 350)
    s.label(1100, 290, "ADC_V1")
    s.text(1112, 310, "0-2.5 V", size=10, color=NOTE)

    s.note(60, 110, [
        "Set point: DAC 0-2.5 V, divided by 5, is the voltage the loop",
        "holds across R105: 0.5 V = 50 mA.",
        "Q101 shorts the set point to ground while LASER_OFF is high.",
        "R106 and R107 leave from R105's own pad (Kelvin); R102, C101",
        "and R105 return to one ground point.",
        "C105: footprint only, fitted if a scope on the prototype asks.",
    ], size=11)

    s.text(60, 590, "Per channel", bold=True, size=13)
    s.table(60, 620,
            ["Ch", "DAC net = U4 output (pin)", "Op-amp: +, −, out",
             "ADC_I: GPIO (DevKit pin)", "ADC_V: GPIO (DevKit pin)",
             "Laser, connector"],
            [
                ["1", "DAC1 = VOUT0 (2)", "U2A: 3, 2, 1", "GPIO1 (J3-4)",
                 "GPIO10 (J1-16)", "laser 1, J101"],
                ["2", "DAC2 = VOUT1 (1)", "U2B: 5, 6, 7", "GPIO2 (J3-5)",
                 "GPIO11 (J1-17)", "laser 2, J201"],
                ["3", "DAC3 = VOUT2 (20)", "U2C: 10, 9, 8", "GPIO4 (J1-4)",
                 "GPIO12 (J1-18)", "laser 3, J301"],
                ["4", "DAC4 = VOUT3 (19)", "U3A: 3, 2, 1", "GPIO5 (J1-5)",
                 "GPIO13 (J1-19)", "laser 4, J401"],
                ["5", "DAC5 = VOUT4 (12)", "U3B: 5, 6, 7", "GPIO6 (J1-6)",
                 "GPIO14 (J1-20)", "laser 5, J501"],
                ["6", "DAC6 = VOUT5 (11)", "U3C: 10, 9, 8", "GPIO7 (J1-7)",
                 "GPIO15 (J1-8)", "laser 6, J601"],
            ],
            [50, 210, 170, 200, 200, 160])
    s.text(60, 770, "SOT-23 pins: 1 gate, 2 source, 3 drain (Q101, Q102); "
           "BAT54: 1 anode, 3 cathode, 2 unconnected.", size=11, color=NOTE)
    s.save(OUT / "laser-board-2-channel.svg")


# ======================================================== sheet 3: DAC
def sheet_dac():
    s = Sch(1240, 800,
            "Laser board, sheet 3 of 4: DAC, I²C, temperature, "
            "decoupling",
            "Everything here runs on +3V3_A, the SKR's side.")

    # --- I2C
    s.text(60, 110, "I²C bus", bold=True, size=13)
    for y0, a, b, r1, r2 in ((230, "ESP_SDA", "SDA", "R5", "R3"),
                             (360, "ESP_SCL", "SCL", "R6", "R4")):
        s.label(130, y0, a, side="l")
        s.line((130, y0), (140, y0))
        s.res_h(140, y0, r1, "330R")
        s.line((200, y0), (300, y0))
        s.dot(250, y0)
        s.res_v(250, y0 - 60, r2, "4.7k")
        s.pwr(250, y0 - 60, "+3V3_A")
        s.label(300, y0, b)
    s.text(60, 400, "ESP_SDA = GPIO8, ESP_SCL = GPIO9", size=10, color=NOTE)

    # --- DAC
    s.ic(560, 150, 180, "U4", "AD5675RBRUZ (TSSOP-20), address 0x0C",
         [(3, "VDD", "+3V3_A"), (4, "VLOGIC", "+3V3_A"),
          (17, "RESET", "+3V3_A"), (5, "SCL", "SCL"), (16, "SDA", "SDA"),
          (6, "A0", "GND"), (7, "A1", "GND"), (8, "GAIN", "GND"),
          (14, "RSTSEL", "GND"), (15, "LDAC", "GND"), (13, "GND", "GND")],
         [(2, "VOUT0", "DAC1"), (1, "VOUT1", "DAC2"), (20, "VOUT2", "DAC3"),
          (19, "VOUT3", "DAC4"), (12, "VOUT4", "DAC5"),
          (11, "VOUT5", "DAC6"), (10, "VOUT6", "DAC7"),
          (9, "VOUT7", "DAC8"), None, (18, "VREFOUT", "VREF")])
    s.text(824, 316, "spare, pad TP6", size=10, color=NOTE)
    s.text(824, 340, "spare, pad TP7", size=10, color=NOTE)
    s.note(560, 450, [
        "GAIN low: outputs span 0-2.5 V (internal reference).",
        "RSTSEL low: every output powers up at zero.",
        "LDAC low: an output changes as it is written.",
        "RESET high: unused.",
    ], size=11)

    # --- op-amp supplies
    s.ic(940, 150, 110, "U2", "MCP6V34-E/SL (SOIC-14)",
         [(4, "VDD", "+3V3_A")], [(11, "VSS", "GND")])
    s.ic(940, 250, 110, "U3", "MCP6V34-E/SL (SOIC-14)",
         [(4, "VDD", "+3V3_A")], [(11, "VSS", "GND")])
    s.text(940, 100, "U2, U3: amplifiers A-C on sheet 2, D on sheet 1.",
           size=10, color=NOTE)

    # --- MCP9600
    s.ic(940, 420, 150, "A2", "MCP9600 breakout, on a socket",
         [("", "VIN", "+3V3_A"), ("", "GND", "GND"), ("", "SCL", "SCL"),
          ("", "SDA", "SDA")],
         [("", "TC+", None), ("", "TC−", None)])
    s.text(1116, 442, "type K", size=10, color=NOTE)
    s.text(1116, 466, "thermocouple", size=10, color=NOTE)
    s.note(880, 550, [
        "Header pin order: from the breakout bought.",
        "Its other pins stay unconnected.",
        "Address 0x60-0x67 as shipped; none clashes with U4.",
    ], size=10)

    # --- decoupling
    s.text(60, 560, "Decoupling, each at the pin named", bold=True, size=13)
    s.line((100, 640), (520, 640))
    s.pwr(100, 640, "+3V3_A")
    caps = [(140, "C7", "100n", "U4-3"), (230, "C8", "10µ", "U4-3"),
            (320, "C9", "100n", "U4-4"), (410, "C11", "100n", "U2-4"),
            (500, "C12", "100n", "U3-4")]
    for x, ref, val, at in caps:
        s.dot(x, 640)
        s.cap_v(x, 640, ref, val)
        s.gnd(x, 700)
        s.text(x, 728, "at " + at, size=10, color=NOTE, anchor="middle")
    s.label(620, 640, "VREF", side="u")
    s.cap_v(620, 640, "C10", "100n")
    s.gnd(620, 700)
    s.text(620, 728, "at U4-18", size=10, color=NOTE, anchor="middle")
    s.save(OUT / "laser-board-3-dac.svg")


# ====================================================== sheet 4: ESP32
def sheet_esp():
    s = Sch(1240, 800,
            "Laser board, sheet 4 of 4: ESP32-S3 DevKit and outputs",
            "The DevKit sits on two 1 × 22 sockets. Its supply is the "
            "Pi's USB: its 5V and 3V3 pins connect to nothing here.")
    j1 = [(1, "3V3", "nc"), (2, "3V3", "nc"), (3, "RST", "nc"),
          (4, "GPIO4", "ADC_I3"), (5, "GPIO5", "ADC_I4"),
          (6, "GPIO6", "ADC_I5"), (7, "GPIO7", "ADC_I6"),
          (8, "GPIO15", "ADC_V6"), (9, "GPIO16", "SKR_IO"),
          (10, "GPIO17", "ADC_RAIL"), (11, "GPIO18", "SPARE18"),
          (12, "GPIO8", "ESP_SDA"), (13, "GPIO3", "nc"),
          (14, "GPIO46", "nc"), (15, "GPIO9", "ESP_SCL"),
          (16, "GPIO10", "ADC_V1"), (17, "GPIO11", "ADC_V2"),
          (18, "GPIO12", "ADC_V3"), (19, "GPIO13", "ADC_V4"),
          (20, "GPIO14", "ADC_V5"), (21, "5V", "nc"), (22, "GND", "GND")]
    j3 = [(1, "GND", "GND"), (2, "TX (GPIO43)", "nc"),
          (3, "RX (GPIO44)", "nc"), (4, "GPIO1", "ADC_I1"),
          (5, "GPIO2", "ADC_I2"), (6, "GPIO42", "AUX"),
          (7, "GPIO41", "SPARE41"), (8, "GPIO40", "LAMP"),
          (9, "GPIO39", "LID_SNS"), (10, "GPIO38 (RGB LED)", "nc"),
          (11, "GPIO37", "nc"), (12, "GPIO36", "nc"), (13, "GPIO35", "nc"),
          (14, "GPIO0", "nc"), (15, "GPIO45", "nc"), (16, "GPIO48", "nc"),
          (17, "GPIO47", "nc"), (18, "GPIO21", "EN"),
          (19, "GPIO20 (USB)", "nc"), (20, "GPIO19 (USB)", "nc"),
          (21, "GND", "GND"), (22, "GND", "GND")]
    s.ic(300, 130, 280, "A1", "ESP32-S3-DevKitC-1-N8R8", j1, j3)
    s.text(300, 698, "J1", bold=True, size=12)
    s.text(580, 698, "J3", bold=True, size=12, anchor="end")
    s.note(60, 720, [
        "J1 and J3 are the DevKit's own header names; pin 1 of each is at "
        "the antenna end.",
        "SPARE18, SPARE41: a pad each. USB to the Pi on the port marked "
        "USB (GPIO19/20), not UART.",
    ], size=11)

    # --- lamp and aux
    for y0, lab, rg, rp, q, d, j, desc, gpio in (
            (200, "LAMP", "R14", "R15", "Q2", "D1", "J12",
             "lamp, 5 V (3-pin)", "GPIO40"),
            (440, "AUX", "R16", "R17", "Q3", "D2", "J13",
             "aux, 5 V (3-pin)", "GPIO42")):
        s.label(880, y0, lab, side="l")
        s.text(868, y0 + 20, gpio, size=10, color=NOTE, anchor="end")
        s.res_h(880, y0, rg, "1k")
        s.line((940, y0), (980, y0))
        s.dot(960, y0)
        s.res_v(960, y0, rp, "100k", side="l")
        s.gnd(960, y0 + 60)
        s.nmos(980, y0, q, "AO3400A")
        s.gnd(1020, y0 + 30)
        s.line((1020, y0 - 30), (1090, y0 - 30))
        s.line((1050, y0 - 90), (1090, y0 - 90))
        s.pwr(1050, y0 - 90, "+5V_L")
        s.dot(1050, y0 - 30)
        s.diode_v(1050, y0 - 90, d, "SS14", length=60, side="l")
        s.conn(1110, y0 - 105, j, desc,
               [(1, "+5 V"), (2, "unused"), (3, "switched −")],
               w=100, pitch=30)
        s.nc(1090, y0 - 60)
    s.note(830, 520, [
        "D1, D2: fitted for a fan or relay; a lamp does not need one.",
        "J10, J12, J13 are 3-pin with the middle pin unused, so a laser's",
        "2-pin plug pushed into one meets a single live pin at most.",
        "Lamp and aux together: about 0.2 A, within F1.",
    ], size=10)

    # --- SKR line
    s.label(880, 640, "SKR_IO", side="l")
    s.text(868, 660, "GPIO16", size=10, color=NOTE, anchor="end")
    s.res_h(880, 640, "R18", "1k")
    s.line((940, 640), (1090, 640))
    s.conn(1110, 620, "J14", "spare line to the SKR",
           [(1, "signal"), (2, "GND")], w=100)
    s.line((1090, 680), (1070, 680), (1070, 690))
    s.gnd(1070, 690)
    s.save(OUT / "laser-board-4-esp32.svg")


sheet_power()
sheet_channel()
sheet_dac()
sheet_esp()
print("ok")
