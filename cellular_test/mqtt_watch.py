"""Subscribe to the MQTT broker your Notehub outbound Route publishes to and print uplink events.

Env: MQTT_HOST (required), MQTT_PORT (1883), MQTT_TOPIC (default "delivery_robot/#"),
     MQTT_USERNAME, MQTT_PASSWORD, MQTT_TLS=1 to enable TLS.
"""

import json
import os
import sys
import time


def format_message(topic, payload):
    try:
        event = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return f"[{topic}] (raw) {payload!r}"
    if not isinstance(event, dict):
        return f"[{topic}] {json.dumps(event)}"
    when = event.get("when")
    stamp = time.strftime("%H:%M:%S", time.localtime(when)) if isinstance(when, (int, float)) else "?"
    return (f"[{topic}] {stamp} device={event.get('device')} file={event.get('file')} "
            f"body={json.dumps(event.get('body'))}")


def main():
    import paho.mqtt.client as mqtt

    host = os.environ.get("MQTT_HOST") or sys.exit("set MQTT_HOST")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    topic = os.environ.get("MQTT_TOPIC", "delivery_robot/#")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if os.environ.get("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.environ.get("MQTT_PASSWORD"))
    if os.environ.get("MQTT_TLS") == "1":
        client.tls_set()

    def on_connect(c, userdata, flags, reason_code, properties):
        print(f"connected to {host}:{port} ({reason_code}); subscribing to {topic!r}")
        c.subscribe(topic)

    def on_message(c, userdata, msg):
        print(format_message(msg.topic, msg.payload), flush=True)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port)
    client.loop_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
