## praniSheba Fire Alarm App Backend (Django + DRF + Channels)

Monolithic Django project providing:
- REST endpoints: `/healthz`, `/readyz`
- Web UI: `/` (map), `/login` (static template)
- WebSocket: `/ws` real-time device updates
- MQTT consumer enriches messages and broadcasts to clients

### Quickstart (local)

1) Python 3.12, then install dependencies:
	- Create a virtualenv and `pip install -r requirements.txt`
2) Copy `.env.example` to `.env` and adjust values (Django SECRET_KEY, DB creds, MQTT, etc.). Do not commit `.env`.
3) Run the ASGI server:
	- `daphne -b 0.0.0.0 -p 8000 config.asgi:application`
4) Open http://localhost:8000
5) Use `device_simulator.py` to generate MQTT messages.

### Docker

`docker compose up --build` then open http://localhost:6066. The container reads configuration from `.env` via `env_file`.

### Structure

- `config/` Django settings, urls, asgi, wsgi
- `api/` DRF endpoints for health
- `realtime/` templates views, WebSocket consumer, MQTT thread
- `templates/` and `static/` unchanged from original
- `device_simulator.py` unchanged
