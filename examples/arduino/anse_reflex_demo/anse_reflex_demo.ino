/*
  ANSE reflex hardware demo — ELEGOO Mega 2560

  Wiring:
    HC-SR04     VCC -> 5V   GND -> GND   TRIG -> D9   ECHO -> D10
    SG90 servo  signal -> D6   (power from 5V/GND)
    DHT11       VCC -> 5V   GND -> GND   DATA/OUT -> D7
    Onboard LED (pin 13) lights while stopped — no wiring needed

  Serial protocol, 9600 baud, newline-terminated:
    Arduino -> PC   "D,<distance_cm>\n"         every ~100ms
                    "T,<temp_c>,<humidity>\n"   every ~2s (DHT11 max rate)
    PC -> Arduino   "STOP\n"              park servo at 0deg, LED on
                    "HOME\n"              servo to 90deg, LED off
                    "S,<angle>\n"         move servo to angle, LED off
                    "ALARM\n"             servo sweep + LED blink (flame reflex), then HOME
*/

#include <Servo.h>
#include <SimpleDHT.h>

const int TRIG_PIN = 9;
const int ECHO_PIN = 10;
const int SERVO_PIN = 6;
const int LED_PIN = 13;
const int DHT_PIN = 7;
const unsigned long SAMPLE_INTERVAL_MS = 100;
const unsigned long DHT_INTERVAL_MS = 2000;

Servo armServo;
SimpleDHT11 dht11(DHT_PIN);
unsigned long lastSampleAt = 0;
unsigned long lastDhtSampleAt = 0;
String incoming;

float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000UL); // 30ms timeout, ~5m range
  if (duration == 0) return -1;
  return duration * 0.0343 / 2.0;
}

void handleCommand(const String &cmd) {
  if (cmd == "STOP") {
    armServo.write(0);
    digitalWrite(LED_PIN, HIGH);
  } else if (cmd == "HOME") {
    armServo.write(90);
    digitalWrite(LED_PIN, LOW);
  } else if (cmd == "ALARM") {
    for (int i = 0; i < 3; i++) {
      digitalWrite(LED_PIN, HIGH);
      armServo.write(180);
      delay(150);
      digitalWrite(LED_PIN, LOW);
      armServo.write(0);
      delay(150);
    }
    armServo.write(90);
    digitalWrite(LED_PIN, LOW);
  } else if (cmd.startsWith("S,")) {
    int angle = cmd.substring(2).toInt();
    angle = constrain(angle, 0, 180);
    armServo.write(angle);
    digitalWrite(LED_PIN, LOW);
  }
}

void setup() {
  Serial.begin(9600);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  armServo.attach(SERVO_PIN);
  armServo.write(90);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      incoming.trim();
      if (incoming.length() > 0) handleCommand(incoming);
      incoming = "";
    } else {
      incoming += c;
    }
  }

  unsigned long now = millis();
  if (now - lastSampleAt >= SAMPLE_INTERVAL_MS) {
    lastSampleAt = now;
    float cm = readDistanceCm();
    if (cm >= 0) {
      Serial.print("D,");
      Serial.println(cm, 1);
    }
  }

  if (now - lastDhtSampleAt >= DHT_INTERVAL_MS) {
    lastDhtSampleAt = now;
    byte temperature = 0;
    byte humidity = 0;
    int err = dht11.read(&temperature, &humidity, NULL);
    if (err == SimpleDHTErrSuccess) {
      Serial.print("T,");
      Serial.print((int)temperature);
      Serial.print(",");
      Serial.println((int)humidity);
    }
  }
}
