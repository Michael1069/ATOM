// ATOM LED Firmware for ESP32 (Arduino framework)
// -------------------------------------------------
// This sketch fimplements the ESP32 side of the ATOM system.
// It connects to Wi‑Fi, subscribes to an MQTT command topic,
// drives GPIO 23 for an LED, and publishes the actual state.
//
// IMPORTANT: Do NOT store Wi‑Fi or MQTT credentials in this file.
// Create a separate "config.h" (ignored by git) that defines the
// required constants. See the accompanying README for details.

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// Include user‑provided configuration (not committed to git)
// This file must define: WIFI_SSID, WIFI_PASSWORD,
// MQTT_BROKER, MQTT_PORT, MQTT_USER, MQTT_PASSWORD.
#include "config.h"

// Pin definitions
const uint8_t LED_PIN = 23; // GPIO23 connected to LED (via resistor)

// MQTT topics
const char* SET_TOPIC   = "atom/appliance/led1/set";   // incoming command
const char* STATE_TOPIC = "atom/appliance/led1/state"; // outgoing state

WiFiClient espClient;
PubSubClient client(espClient);

// Forward declarations
void connectToWiFi();
void connectToMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
void publishState(const char* state);

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- ATOM LED Firmware starting ---");

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW); // ensure LED is off at start

  // Publish initial state after a short delay to give Wi‑Fi time to settle
  connectToWiFi();
  connectToMQTT();
  publishState(digitalRead(LED_PIN) == HIGH ? "on" : "off");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi‑Fi disconnected – reconnecting...");
    connectToWiFi();
  }

  if (!client.connected()) {
    Serial.println("MQTT disconnected – reconnecting...");
    connectToMQTT();
  }
  client.loop();
}

void connectToWiFi() {
  Serial.printf("Connecting to Wi‑Fi SSID: %s\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long startAttemptTime = millis();
  // Wait up to 20 seconds for connection
  while (WiFi.status() != WL_CONNECTED && millis() - startAttemptTime < 20000) {
    delay(500);
    Serial.print('.');
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("\nWi‑Fi connected, IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nFailed to connect to Wi‑Fi.");
  }
}

void connectToMQTT() {
  client.setServer(MQTT_BROKER, MQTT_PORT);
  client.setCallback(mqttCallback);

  Serial.printf("Connecting to MQTT broker %s:%d\n", MQTT_BROKER, MQTT_PORT);
  while (!client.connected()) {
    // client.connect returns bool – pass client id, user, password
    String clientId = "ATOM_LED_" + String(ESP.getEfuseMac());
    if (client.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD)) {
      Serial.println("MQTT connected");
      // Subscribe to command topic
      if (client.subscribe(SET_TOPIC)) {
        Serial.print("Subscribed to ");
        Serial.println(SET_TOPIC);
      } else {
        Serial.print("Failed to subscribe to ");
        Serial.println(SET_TOPIC);
      }
    } else {
      Serial.print("MQTT connection failed, rc=");
      Serial.print(client.state());
      Serial.println(" – retrying in 2s");
      delay(2000);
    }
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.print("Message arrived on topic ");
  Serial.println(topic);

  // Ensure we only handle the expected topic
  if (strcmp(topic, SET_TOPIC) != 0) {
    Serial.println("Unexpected topic – ignoring");
    return;
  }

  // Copy payload to a null‑terminated string for JSON parsing
  char jsonBuffer[256];
  if (length >= sizeof(jsonBuffer)) {
    Serial.println("Payload too large – ignoring");
    return;
  }
  memcpy(jsonBuffer, payload, length);
  jsonBuffer[length] = '\0';

  // Parse JSON
  StaticJsonDocument<200> doc;
  DeserializationError err = deserializeJson(doc, jsonBuffer);
  if (err) {
    Serial.print("JSON parse error: ");
    Serial.println(err.c_str());
    return;
  }

  const char* state = doc["state"];
  if (!state) {
    Serial.println("No \"state\" field – ignoring");
    return;
  }

  Serial.print("Command state: ");
  Serial.println(state);

  if (strcmp(state, "on") == 0) {
    digitalWrite(LED_PIN, HIGH);
    publishState("on");
  } else if (strcmp(state, "off") == 0) {
    digitalWrite(LED_PIN, LOW);
    publishState("off");
  } else {
    Serial.println("Unknown state value – ignoring");
  }
}

void publishState(const char* state) {
  // Build JSON payload {"state":"on/off","timestamp":<ISO‑8601 UTC>}
  StaticJsonDocument<200> doc;
  doc["state"] = state;
  // Get UTC timestamp in ISO‑8601 format
  time_t now = time(nullptr);
  struct tm* utc = gmtime(&now);
  char ts[32];
  strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%SZ", utc);
  doc["timestamp"] = ts;

  char buffer[256];
  size_t n = serializeJson(doc, buffer);
  if (client.publish(STATE_TOPIC, buffer, n)) {
    Serial.print("Published state to ");
    Serial.print(STATE_TOPIC);
    Serial.print(": ");
    Serial.println(buffer);
  } else {
    Serial.println("Failed to publish state");
  }
}

