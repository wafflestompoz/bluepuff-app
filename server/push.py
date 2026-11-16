"""Push notices to members' phones through Expo's push service (works for iOS and Android builds of the Expo app)."""
import json, urllib.request

EXPO_URL = "https://exp.host/--/api/v2/push/send"


def expo_send(tokens, title, body, data=None):
    """Send one message to many Expo push tokens, 100 per request. Returns how many were accepted."""
    sent = 0
    for i in range(0, len(tokens), 100):
        msgs = [{"to": t, "title": title, "body": body, "data": data or {}, "sound": "default"} for t in tokens[i:i + 100]]
        req = urllib.request.Request(EXPO_URL, data=json.dumps(msgs).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            sent += sum(1 for t in json.load(r).get("data", []) if t.get("status") == "ok")
    return sent


SENDER = {"fn": expo_send}      # tests swap this out


def send(tokens, title, body, data=None):
    return SENDER["fn"](tokens, title, body, data) if tokens else 0
