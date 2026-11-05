// MultiLBIC laser board - Seeeduino Xiao (SAMD21)
//
// Six laser enables and a servo that turns the laser revolver. The
// protocol is in docs/devices.md. Every command gets exactly one reply
// line: a value, "OK ...", or "ERR <reason>".
//
//   ID?            -> MultiLBIC-Laser,2.1.0
//   STATE?         -> STATE <laser 0-6> <servo angle>
//   ANGLES?        -> ANGLES 150 90 30 150 90 30
//   SETTLE?        -> SETTLE <ms>
//   SETTLE <ms>    -> OK SETTLE <ms>          (0..10000)
//   LASER <1-6>    -> OK LASER <n>            (after the servo settles)
//   LASER 0 | OFF  -> OK OFF
//   RELEASE?       -> RELEASE <0|1>
//   RELEASE <0|1>  -> OK RELEASE <0|1>
//   anything else  -> ERR UNKNOWN
//
// Changes from the original sketch (1.x):
// - a reply protocol, identification and a state query;
// - the settle time can be set instead of a fixed 2 s, and is skipped
//   when the servo is already at the right angle (lasers 1/4, 2/5 and
//   3/6 share an angle);
// - LASER 0 turns everything off without parking the servo.
//
// 2.1.0 (2026-11-05): once the servo has turned and settled it is
// released (no more pulses, so it stops correcting itself) and attached
// again only for the next turn; the gearbox holds the revolver. Held
// powered, it moved the beam in steps of 7-24 um at random times, all
// the same way, for minutes after a turn and even with nothing else
// moving (bench, 2026-11-05). RELEASE 0 keeps it powered, as 2.0.0 did.
// The default is on; a power-up forgets a runtime change.
//
// Pins and angles are unchanged.

#include <Servo.h>

const char *FIRMWARE_ID = "MultiLBIC-Laser,2.1.0";

const int LASER_COUNT = 6;
const int laserPins[LASER_COUNT] = {1, 2, 3, 4, 5, 8};
const int laserAngles[LASER_COUNT] = {150, 90, 30, 150, 90, 30};
const int servoPin = 9;
const int startAngle = 90;
const unsigned long MAX_SETTLE_MS = 10000;

unsigned long settleMs = 2000;
bool releaseServo = true;
int activeLaser = 0;  // 0 = all off
int servoAngle = startAngle;

Servo servo;

void allOff() {
  for (int i = 0; i < LASER_COUNT; i++) {
    digitalWrite(laserPins[i], LOW);
  }
  activeLaser = 0;
}

// True if `text` is a non-empty string of decimal digits.
bool isNumber(const String &text) {
  if (text.length() == 0) return false;
  for (unsigned int i = 0; i < text.length(); i++) {
    if (!isDigit(text.charAt(i))) return false;
  }
  return true;
}

void selectLaser(int n) {
  allOff();
  int target = laserAngles[n - 1];
  if (target != servoAngle) {
    if (!servo.attached()) {
      servo.attach(servoPin);
    }
    servo.write(target);
    servoAngle = target;
    delay(settleMs);
    if (releaseServo) {
      servo.detach();
    }
  }
  digitalWrite(laserPins[n - 1], HIGH);
  activeLaser = n;
  Serial.print("OK LASER ");
  Serial.println(n);
}

void handle(const String &command) {
  if (command == "ID?") {
    Serial.println(FIRMWARE_ID);
  } else if (command == "STATE?") {
    Serial.print("STATE ");
    Serial.print(activeLaser);
    Serial.print(" ");
    Serial.println(servoAngle);
  } else if (command == "ANGLES?") {
    Serial.print("ANGLES");
    for (int i = 0; i < LASER_COUNT; i++) {
      Serial.print(" ");
      Serial.print(laserAngles[i]);
    }
    Serial.println();
  } else if (command == "SETTLE?") {
    Serial.print("SETTLE ");
    Serial.println(settleMs);
  } else if (command.startsWith("SETTLE ")) {
    String value = command.substring(7);
    if (!isNumber(value) || (unsigned long)value.toInt() > MAX_SETTLE_MS) {
      Serial.println("ERR BAD_VALUE");
      return;
    }
    settleMs = value.toInt();
    Serial.print("OK SETTLE ");
    Serial.println(settleMs);
  } else if (command == "RELEASE?") {
    Serial.print("RELEASE ");
    Serial.println(releaseServo ? 1 : 0);
  } else if (command == "RELEASE 0" || command == "RELEASE 1") {
    releaseServo = command == "RELEASE 1";
    if (releaseServo && servo.attached()) {
      servo.detach();
    } else if (!releaseServo && !servo.attached()) {
      servo.attach(servoPin);
      servo.write(servoAngle);
    }
    Serial.print("OK RELEASE ");
    Serial.println(releaseServo ? 1 : 0);
  } else if (command == "OFF" || command == "LASER 0") {
    allOff();
    Serial.println("OK OFF");
  } else if (command.startsWith("LASER ")) {
    String value = command.substring(6);
    int n = value.toInt();
    if (!isNumber(value) || n < 1 || n > LASER_COUNT) {
      Serial.println("ERR BAD_LASER");
      return;
    }
    selectLaser(n);
  } else {
    Serial.println("ERR UNKNOWN");
  }
}

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < LASER_COUNT; i++) {
    pinMode(laserPins[i], OUTPUT);
  }
  allOff();
  servo.attach(servoPin);
  servo.write(startAngle);
  servoAngle = startAngle;
  if (releaseServo) {
    delay(settleMs);
    servo.detach();
  }
  // Lost if no host has the port open yet, which is fine: the host
  // identifies the board with ID? rather than waiting for this.
  Serial.print("READY ");
  Serial.println(FIRMWARE_ID);
}

void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command.length() > 0) {
      handle(command);
    }
  }
}
