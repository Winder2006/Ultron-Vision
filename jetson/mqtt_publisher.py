"""
MQTT publisher implementing Mother's vision contract.

Topics (prefix "mother/vision/"), JSON payloads, epoch seconds in ts:
  face_detected   {"name": str, "confidence": float, "ts": int}
  face_lost       {"name": str, "ts": int}
  object_detected {"label": str, "confidence": float, "ts": int}
  room_occupancy  {"occupied": bool, "person_count": int, "ts": int}  [retained]

Events only — never frames or video.
"""

import json
import logging
import socket
import time
import uuid
from typing import Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

TOPIC_PREFIX = "mother/vision/"


def _make_client_id() -> str:
    host = socket.gethostname().split(".")[0]
    return "ultron-vision-{}-{}".format(host, uuid.uuid4().hex[:8])


class VisionPublisher:
    """Thin wrapper around paho-mqtt for the Mother vision contract."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1883,
        client_id: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.client_id = client_id or _make_client_id()

        # paho-mqtt 2.x requires an explicit callback API version;
        # fall back to the 1.x constructor if running an older paho.
        try:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id
            )
        except AttributeError:
            self._client = mqtt.Client(client_id=self.client_id)

        if username:
            self._client.username_pw_set(username, password)

        # Optional (not part of the contract): retained status topic with a
        # Last Will so Mother can tell the service itself died vs. just quiet.
        self._client.will_set(
            TOPIC_PREFIX + "status",
            json.dumps({"online": False}),
            qos=1,
            retain=True,
        )

        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    # paho v1 and v2 pass different arguments — accept anything.
    def _on_connect(self, *args, **kwargs):
        logger.info(
            "MQTT connected to %s:%s as %s", self.host, self.port, self.client_id
        )
        self._client.publish(
            TOPIC_PREFIX + "status",
            json.dumps({"online": True}),
            qos=1,
            retain=True,
        )

    def _on_disconnect(self, *args, **kwargs):
        logger.warning("MQTT disconnected — paho will auto-reconnect")

    def connect(self):
        self._client.connect(self.host, self.port, keepalive=30)
        self._client.loop_start()

    def close(self):
        try:
            self._client.publish(
                TOPIC_PREFIX + "status",
                json.dumps({"online": False}),
                qos=1,
                retain=True,
            )
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Contract topics
    # ------------------------------------------------------------------

    def _publish(self, topic: str, payload: dict, retain: bool = False):
        data = json.dumps(payload, separators=(",", ":"))
        # QoS 1: queued and re-sent across broker reconnects.
        result = self._client.publish(TOPIC_PREFIX + topic, data, qos=1, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("MQTT publish %s rc=%s (queued for retry)", topic, result.rc)
        else:
            logger.debug("MQTT %s %s", topic, data)

    @staticmethod
    def _ts(ts: Optional[int]) -> int:
        return int(ts if ts is not None else time.time())

    def face_detected(self, name: str, confidence: float, ts: Optional[int] = None):
        self._publish(
            "face_detected",
            {"name": name, "confidence": round(float(confidence), 2), "ts": self._ts(ts)},
        )

    def face_lost(self, name: str, ts: Optional[int] = None):
        self._publish("face_lost", {"name": name, "ts": self._ts(ts)})

    def object_detected(self, label: str, confidence: float, ts: Optional[int] = None):
        self._publish(
            "object_detected",
            {"label": label, "confidence": round(float(confidence), 2), "ts": self._ts(ts)},
        )

    def room_occupancy(self, occupied: bool, person_count: int, ts: Optional[int] = None):
        # Retained so a freshly-connected Mother immediately knows current state.
        self._publish(
            "room_occupancy",
            {"occupied": bool(occupied), "person_count": int(person_count), "ts": self._ts(ts)},
            retain=True,
        )
