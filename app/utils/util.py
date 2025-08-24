from fastapi import UploadFile
from fastapi import HTTPException  # ← AÑADE ESTA IMPORTACIÓN
import os
import uuid

async def upload_file_to_storage(file: UploadFile, folder: str):
    # Implementación de ejemplo para almacenamiento local
    import os
    from fastapi import UploadFile
    
    upload_dir = f"static/uploads/{folder}"
    os.makedirs(upload_dir, exist_ok=True)
    
    file_path = f"{upload_dir}/{file.filename}"
    
    with open(file_path, "wb") as buffer: 
        content = await file.read()
        buffer.write(content)
    
    return f"/{file_path}"  # URL relativa

async def upload_file_to_storage_post(file: UploadFile, folder: str):
    """
    Sube un archivo al almacenamiento local y devuelve la URL relativa
    """
    try:
        # Crear directorio si no existe
        upload_dir = f"static/uploads/{folder}"
        os.makedirs(upload_dir, exist_ok=True)
        
        # Generar nombre único para el archivo
        file_extension = file.filename.split('.')[-1] if '.' in file.filename else ''
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        
        # Ruta completa del archivo
        file_path = os.path.join(upload_dir, unique_filename)
        
        # Guardar el archivo
        with open(file_path, "wb") as buffer: 
            content = await file.read()
            buffer.write(content)
        
        return f"/{file_path}"  # URL relativa
        
    except Exception as e:
        # Ahora HTTPException está definido
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir el archivo: {str(e)}"
        )