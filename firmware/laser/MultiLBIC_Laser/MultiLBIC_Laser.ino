#include <Servo.h>

const int laserPins[] = { 1, 2, 3, 4, 5, 8 };
const int laserAngles[] = { 150, 90, 30, 150, 90, 30 };
const int servoPin = 9;

unsigned long prevTime, currTime;

unsigned long waitTime = 2000;

Servo myServo;


void setup() {
  // put your setup code here, to run once:
  Serial.begin(115200);
  myServo.attach(servoPin);
  myServo.write(90);  // Default position

  for (int i = 0; i < 6; i++) {
    pinMode(laserPins[i], OUTPUT);
    digitalWrite(laserPins[i], LOW);  // Ensure lasers start off
  }
}

void loop() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command.startsWith("LASER")) {

      // Turn off all lasers
      for (int i = 0; i < 6; i++) {
        digitalWrite(laserPins[i], LOW);
      }

      int laserNum = command.substring(6).toInt();
      if (laserNum >= 1 && laserNum <= 6) {

        myServo.write(laserAngles[laserNum - 1]);
        Serial.print("Servo moved to: ");
        Serial.println(laserAngles[laserNum - 1]);

        currTime = millis();
        prevTime = millis();

        while (currTime - prevTime < waitTime) {

          currTime = millis();
        }

        // Turn on the selected laser
        digitalWrite(laserPins[laserNum - 1], HIGH);
        Serial.print("Laser ");
        Serial.print(laserNum);
        Serial.println(" ON (all others OFF)");
      } else {

        myServo.write(90);
        Serial.println("Servo moved to: 90");

        currTime = millis();
        prevTime = millis();

        while (currTime - prevTime < waitTime) {

          currTime = millis();
        }

        // Turn off all lasers
        for (int i = 0; i < 6; i++) {
          digitalWrite(laserPins[i], LOW);
        }
        Serial.println("All lasers OFF");
      }
    }
  }
}