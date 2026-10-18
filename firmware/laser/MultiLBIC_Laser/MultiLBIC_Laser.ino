// MultiLBIC laser board - Seeeduino Xiao (SAMD21)
//
// Six laser enables and a servo that turns the laser revolver. The
// protocol is in docs/devices.md. Every command gets exactly one reply
// line: a value, "OK ...", or "ERR <reason>".
//
//   ID?            -> MultiLBIC-Laser,2.0.0
//   STATE?         -> STATE <laser 0-6> <servo angle>
//   ANGLES?        -> ANGLES 150 90 30 150 90 30
//   SETTLE?        -> SETTLE <ms>
//   SETTLE <ms>    -> OK SETTLE <ms>          (0..10000)
//   LASER <1-6>    -> OK LASER <n>            (after the servo settles)
//   LASER 0 | OFF  -> OK OFF
//   anything else  -> ERR UNKNOWN
//
// Changes from the original sketch (1.x):
// - a reply protocol, identification and a state query;
// - the settle time can be set instead of a fixed 2 s, and is skipped
//   when the servo is already at the right angle (lasers 1/4, 2/5 and
//   3/6 share an angle);
// - LASER 0 turns everything off without parking the servo.
//
// Pins and angles are unchanged.

#include <Servo.h>

const char *FIRMWARE_ID = "MultiLBIC-Laser,2.0.0";

const int LASER_COUNT = 6;
const int laserPins[LASER_COUNT] = {1, 2, 3, 4, 5, 8};
const int laserAngles[LASER_COUNT] = {150, 90, 30, 150, 90, 30};
const int servoPin = 9;
const int startAngle = 90;
const unsigned long MAX_SETTLE_MS = 10000;

unsigned long settleMs = 2000;
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
    servo.write(target);
    servoAngle = target;
    delay(settleMs);
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
