from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import asyncio
import paho.mqtt.client as mqtt

app = FastAPI()
devices = {}  # deviceID -> device info dict
websockets = set()

# MQTT configuration
MQTT_BROKER = "152.42.179.228"
MQTT_PORT = 1885
MQTT_TOPIC = "aps/fire/data"
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/login", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# MQTT on_message callback
def on_message(client, userdata, msg):
    data = msg.payload.decode()
    # Example data format: "deviceID,GasVal,GasStatus,temperature,humidity,longitude,latitude"
    parts = data.strip().split(",")
    device = {
        "deviceID": parts[0],
        "GasVal": int(parts[1]),
        "GasStatus": int(parts[2]),
        "temperature": int(parts[3]),
        "humidity": int(parts[4]),
        "longitude": parts[5],
        "latitude": parts[6],
    }
    devices[device["deviceID"]] = device
    # Send update to all websockets
    asyncio.run(send_update_to_websockets(device))


async def send_update_to_websockets(device):
    for ws in list(websockets):
        try:
            await ws.send_json(device)
        except:
            websockets.discard(ws)


@app.on_event("startup")
def startup():
    def mqtt_loop():
        client = mqtt.Client()
        client.username_pw_set("apsIoT", "apsIoT25")
        client.on_message = on_message
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.subscribe(MQTT_TOPIC)
        client.loop_forever()

    import threading

    thread = threading.Thread(target=mqtt_loop)
    thread.daemon = True
    thread.start()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    websockets.add(ws)
    # On connect, send all known devices
    for device in devices.values():
        await ws.send_json(device)
    try:
        while True:
            await ws.receive_text()  # Keep connection alive
    except:
        websockets.discard(ws)
