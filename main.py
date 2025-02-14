from fastapi import FastAPI, HTTPException, UploadFile, File, status, Request
from pydantic import BaseModel, Field
import httpx
from typing import List, Dict, Optional
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os
import uuid
from pathlib import Path
import logging
import traceback

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GIS API Gateway",
    description="API для работы с геоинформационной системой",
    version="2.0",
    docs_url="/docs",
    redoc_url=None
)

# Конфигурация
BASE_URL = "https://geois2.orb.ru/api"
TIMEOUT = 30.0
CREDENTIALS = {
    "username": "hackathon_37",
    "password": "hackathon_37_25"
}
DEFAULT_LAYER_ID = 8863
IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True, parents=True)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_MIME_TYPES = [
    "image/jpeg", "image/png", 
    "image/gif", "image/svg+xml",
    "application/pdf"
]

# Подключаем статическую папку
app.mount("/images", StaticFiles(directory="images"), name="images")

# Модели данных
class GeoFeature(BaseModel):
    extensions: Dict = Field(
        default={"attachment": None, "description": None},
        example={"attachment": None, "description": "Описание объекта"}
    )
    fields: Dict = Field(
        ...,
        example={
            "num": 1,
            "n_raion": "Тюльганский район",
            "fio": "Иванов Иван Иванович",
            "years": "1980-1990",
            "info": "Дополнительная информация",
            "kontrakt": "Контрактная служба",
            "nagrads": "Награды"
        }
    )
    geom: str = Field(
        ...,
        example="POINT (6266521.594576891 6868838.029030548)",
        description="Координаты в формате EPSG 3857"
    )

class AttachmentResponse(BaseModel):
    id: str
    name: str
    size: int
    mime_type: str
    url: str

class FeatureCreateResponse(BaseModel):
    id: int

class FeatureResponse(GeoFeature):
    id: int
    attachments: List[AttachmentResponse] = []

# Служебные функции
async def send_request(
    method: str,
    endpoint: str,
    data=None,
    files=None,
    json_data=None,
    params=None
):
    try:
        async with httpx.AsyncClient(
            auth=(CREDENTIALS["username"], CREDENTIALS["password"]),
            timeout=TIMEOUT
        ) as client:
            logger.info(f"Sending request with params: {params}")
            response = await client.request(
                method=method,
                url=f"{BASE_URL}{endpoint}",
                data=data,
                files=files,
                json=json_data,
                params=params
            )
            logger.info(f"Response status: {response.status_code}")
            response.raise_for_status()
            
            if response.headers.get("content-type") == "application/json":
                return response.json()
            return {"status": "success", "response": response.text}
            
    except httpx.HTTPStatusError as e:
        logger.error(f"API error: {e.response.text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Ошибка API ({e.response.status_code}): {e.response.text}"
        )
    except Exception as e:
        logger.error(f"System error: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )

def save_uploaded_file(file: UploadFile) -> str:
    try:
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise ValueError(f"Неподдерживаемый тип файла: {file.content_type}")
            
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            raise ValueError(f"Размер файла ({file_size} bytes) превышает {MAX_FILE_SIZE} bytes")

        file_ext = os.path.splitext(file.filename)[1]
        file_name = f"{uuid.uuid4()}{file_ext}"
        file_path = IMAGES_DIR / file_name
        
        with open(file_path, "wb") as buffer:
            content = file.file.read()
            buffer.write(content)
            
        logger.info(f"Файл сохранен: {file_path.absolute()}")
        return file_name
        
    except Exception as e:
        logger.error(f"Ошибка сохранения файла: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

# Эндпоинты
@app.post("/features/", response_model=FeatureCreateResponse, tags=["Объекты"])
async def create_feature(feature: GeoFeature, layer_id: int = DEFAULT_LAYER_ID):
    """Создать новый объект"""
    response = await send_request(
        "POST",
        f"/resource/{layer_id}/feature/",
        json_data=feature.dict()
    )
    
    # Добавьте валидацию ответа
    if not isinstance(response, dict) or 'id' not in response:
        logger.error(f"Некорректный ответ от API: {response}")
        raise HTTPException(500, "Ошибка создания объекта")
        
    return response

@app.post("/features/{feature_id}/attachments/", response_model=AttachmentResponse, tags=["Вложения"])
async def upload_attachment(
    feature_id: int,
    file: UploadFile = File(...),
    layer_id: int = DEFAULT_LAYER_ID
):
    """Загрузить и прикрепить файл к объекту"""
    try:
        saved_filename = save_uploaded_file(file)
        file_path = IMAGES_DIR / saved_filename
        file_size = os.path.getsize(file_path)
        
        with open(file_path, "rb") as f:
            content = f.read()

        upload_response = await send_request(
            "POST",
            "/component/file_upload/",
            data={"name": file.filename},
            files={"file": (file.filename, content, file.content_type)}
        )

        if not isinstance(upload_response, dict) or 'upload_meta' not in upload_response:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Некорректный ответ от сервера загрузки файлов"
            )

        file_id = upload_response["upload_meta"][0]["id"]
        file_size = os.path.getsize(file_path)

        await send_request(
            "POST",
            f"/resource/{layer_id}/feature/{feature_id}/attachment/",
            json_data={
                "name": file.filename,
                "size": file_size,
                "mime_type": file.content_type,
                "file_upload": {
                    "id": file_id,
                    "size": file_size
                }
            }
        )
        
        return {
            "id": file_id,
            "name": file.filename,
            "size": file_size,
            "mime_type": file.content_type,
            "url": f"/images/{saved_filename}"
        }
        
    except Exception as e:
        logger.error(f"Ошибка загрузки файла: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки файла: {str(e)}"
        )

@app.get("/features/{feature_id}", response_model=FeatureResponse, tags=["Объекты"])
async def get_feature(feature_id: int, layer_id: int = DEFAULT_LAYER_ID):
    """Получить объект по ID"""
    return await send_request(
        "GET",
        f"/resource/{layer_id}/feature/{feature_id}"
    )

@app.get("/features/", response_model=List[FeatureResponse], tags=["Объекты"])
async def get_all_features(
    request: Request,
    layer_id: int = DEFAULT_LAYER_ID,
    kontrakt: Optional[str] = None,
    n_raion: Optional[str] = None
):
    """
    Получить объекты с фильтрацией
    
    Параметры:
    - kontrakt: Точное совпадение места службы (например: СВО)
    - n_raion: Точное совпадение района (например: Тюльганский район)
    """
    params = dict(request.query_params)
    
    if kontrakt:
        params["fields__kontrakt"] = kontrakt
    if n_raion:
        params["fields__n_raion"] = n_raion
    
    response = await send_request(
        "GET",
        f"/resource/{layer_id}/feature/",
        params=params
    )
    
    # Дополнительная фильтрация если API проигнорировало параметры
    filtered_response = response
    if isinstance(response, list):
        if kontrakt:
            filtered_response = [item for item in filtered_response if item.get("fields", {}).get("kontrakt") == kontrakt]
        if n_raion:
            filtered_response = [item for item in filtered_response if item.get("fields", {}).get("n_raion") == n_raion]
    
    return filtered_response

@app.put("/features/{feature_id}/", response_model=FeatureResponse, tags=["Объекты"])
async def update_feature(
    feature_id: int,
    feature: GeoFeature,
    layer_id: int = DEFAULT_LAYER_ID
):
    """Обновить объект"""
    return await send_request(
        "PUT",
        f"/resource/{layer_id}/feature/{feature_id}",
        json_data=feature.dict()
    )

@app.delete("/features/", tags=["Объекты"])
async def delete_features(
    feature_ids: List[int],
    layer_id: int = DEFAULT_LAYER_ID
):
    """Удалить объекты"""
    if not feature_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не указаны ID объектов"
        )
    
    return await send_request(
        "DELETE",
        f"/resource/{layer_id}/feature/",
        json_data=[{"id": fid} for fid in feature_ids]
    )

@app.delete("/features/{feature_id}/attachments/{attachment_id}", tags=["Вложения"])
async def delete_attachment(
    feature_id: int,
    attachment_id: str,
    layer_id: int = DEFAULT_LAYER_ID
):
    """Удалить вложение"""
    return await send_request(
        "DELETE",
        f"/resource/{layer_id}/feature/{feature_id}/attachment/{attachment_id}"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)