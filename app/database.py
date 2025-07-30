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
        # 1. Listar todos los índices existentes
        existing_indexes = await db.users.index_information()
        
        # 2. Eliminar solo los índices problemáticos si existen
        indexes_to_remove = [
            "users_friends", 
            "users_friend_requests",
            "users_sent_requests",
            "users_relationships"
        ]
        
        for index_name in indexes_to_remove:
            try:
                if index_name in existing_indexes:
                    await db.users.drop_index(index_name)
                    logger.info(f"Índice {index_name} eliminado")
            except Exception as e:
                logger.warning(f"No se pudo eliminar el índice {index_name}: {str(e)}")
                continue

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
        # Índices para posts (NUEVO)
        post_indexes = [
            IndexModel([("created_at", DESCENDING)], name="posts_created_at_desc"),
            IndexModel([("author_id", 1)], name="posts_author_id"),
            IndexModel([("author_id", 1), ("created_at", DESCENDING)], name="posts_author_created"),
            IndexModel([("liked_by", 1)], name="posts_liked_by")
        ]
        await db.posts.create_indexes(post_indexes)
        logger.info("Índices creados para la colección 'posts'")

        # Índices para users (NUEVO)
        # Eliminar todos los índices existentes en users
        await db.users.drop_indexes()
        
        # Crear solo índices esenciales
        user_indexes = [
            IndexModel([("username", 1)], name="username_unique", unique=True),
            IndexModel([("email", 1)], name="email_unique", unique=True),
            IndexModel([("relationships", 1)], name="relationships_index")
        ]
        await db.users.create_indexes(user_indexes)
        logger.info("Índices creados para la colección 'users'")

        # Índices para comments (NUEVO)
        comment_indexes = [
            IndexModel([("post_id", 1)], name="comments_post_id"),
            IndexModel([("post_id", 1), ("created_at", DESCENDING)], name="comments_post_created"),
            IndexModel([("author_id", 1)], name="comments_author_id")
        ]
        await db.comments.create_indexes(comment_indexes)
        logger.info("Índices creados para la colección 'comments'")
        
    except Exception as e:
        logger.error(f"Error al inicializar la base de datos: {str(e)}")
        raise

# Llamar a la inicialización cuando el módulo se importe
import asyncio
asyncio.create_task(initialize_database())