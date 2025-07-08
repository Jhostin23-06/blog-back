import asyncio
import websockets
import json

async def test_websocket():
    # Conéctate al WebSocket (ajusta la URL)
    uri = "ws://localhost:8000/ws/685edcb3791a9c4388895640"
    async with websockets.connect(uri) as websocket:
        print("Conectado al WebSocket. Esperando comentarios...")
        while True:
            response = await websocket.recv()
            data = json.loads(response)
            print(f"Nuevo comentario recibido: {data}")

asyncio.get_event_loop().run_until_complete(test_websocket())