from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel, DESCENDING
import logging

logger = logging.getLogger(__name__)

MONGO_URI = "mongodb+srv://urbano:ur.dbMongoDB@cluster0.avnsluf.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "blog_db"

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

async def initialize_database():
    """Inicializa las colecciones y los índices necesarios"""
    try:
        # Crear colección de notificaciones si no existe
        if "notifications" not in (await db.list_collection_names()):
            await db.create_collection("notifications")
            logger.info("Colección 'notifications' creada")
        
        # Crear índices para la colección de notificaciones
        notification_indexes = [
            IndexModel([("user_id", 1)], name="user_id_index"),
            IndexModel([("read", 1)], name="read_status_index"),
            IndexModel([("created_at", DESCENDING)], name="created_at_desc_index"),
            IndexModel([("type", 1)], name="notification_type_index")
        ]
        
        await db.notifications.create_indexes(notification_indexes)
        logger.info("Índices creados para la colección 'notifications'")
        
        # Puedes agregar inicializaciones para otras colecciones aquí
        # ...
        
    except Exception as e:
        logger.error(f"Error al inicializar la base de datos: {str(e)}")
        raise

# Llamar a la inicialización cuando el módulo se importe
import asyncio
asyncio.create_task(initialize_database())