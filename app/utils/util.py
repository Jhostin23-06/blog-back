from fastapi import UploadFile

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