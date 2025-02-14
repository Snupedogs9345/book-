from fastapi import FastAPI, HTTPException, UploadFile, File, status, Request, Depends
from pydantic import BaseModel, Field
import httpx
from typing import List, Dict, Optional

app = FastAPI(
    title="GIS API Gateway",
    description="API для работы с геоинформационной системой",
    version="2.0",
    docs_url="/docs",
    redoc_url=None
)

# Конфигурация
BASE_URL = "https://geois2.orb.ru/api"
TIMEOUT = 10.0
CREDENTIALS = {
    "username": "hackathon_37",
    "password": "hackathon_37_25"
}
DEFAULT_LAYER_ID = 8863

# Модели данных с примерами
class GeoFeature(BaseModel):
    extensions: Dict = Field(
        default={"attachment": None, "description": None},
        example={"attachment": None, "description": None}
    )
    fields: Dict = Field(
        ...,
        example={
            "num": 1,
            "n_raion": "",
            "fio": "",
            "years": "",
            "info": "",
            "kontrakt": "",
            "nagrads": ""
        }
    )
    geom: str = Field(
        ...,
        example="POINT (6266521.594576891 6868838.029030548)",
        description="Координаты в формате EPSG 3857"
    )

class FileAttachment(BaseModel):
    name: str = Field(..., example="photo_2024-05-27_23-26-38.jpg")
    size: int = Field(..., example=100110)
    mime_type: str = Field(..., example="image/jpeg")
    file_upload: Dict = Field(
        ...,
        example={
            "id": "0194c613ab11e91de00ac5b990b5fa6d",
            "size": 100110
        }
    )

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
            
            response = await client.request(
                method=method,
                url=f"{BASE_URL}{endpoint}",
                data=data,
                files=files,
                json=json_data,
                params=params
            )
            response.raise_for_status()
            return response.json() if response.content else {"status": "success"}
            
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка API: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Системная ошибка: {str(e)}"
        )

def get_query_params(request: Request):
    return dict(request.query_params)

# Эндпоинты
@app.post("/features/", tags=["Объекты"], summary="Создать новый объект")
async def create_feature(feature: GeoFeature, layer_id: int = DEFAULT_LAYER_ID):
    return await send_request(
        "POST",
        f"/resource/{layer_id}/feature/",
        json_data=feature.dict()
    )

@app.get(
    "/features/{feature_id}",
    tags=["Объекты"],
    summary="Получить объект по ID",
    responses={
        200: {
            "description": "Данные объекта",
            "content": {
                "application/json": {
                    "example": {
                        "id": 1,
                        "geom": "POINT(6266521.59457689 6868838.02903055)",
                        "fields": {
                            "num": 1,
                            "n_raion": "Тюльганский район",
                            "fio": "Сидоров Сидор Сидорович",
                            "years": "14.10.1961 – 02.01.1982",
                            "info": "Полное описание...",
                            "kontrakt": "Боевые действия в Афганистане",
                            "nagrads": "Орден Красной Звезды"
                        },
                        "extensions": {
                            "attachment": [{
                                "id": 875159,
                                "name": "photo.jpg",
                                "size": 100110,
                                "mime_type": "image/jpeg"
                            }]
                        }
                    }
                }
            }
        }
    }
)
async def get_feature(
    feature_id: int,
    layer_id: int = DEFAULT_LAYER_ID,
    request: Request = None
):
    try:
        return await send_request(
            "GET",
            f"/resource/{layer_id}/feature/{feature_id}"  # УБРАН ЗАКЛЮЧИТЕЛЬНЫЙ СЛЕШ
        )
    except HTTPException as e:
        print(f"Error during request: {e.detail}")
        raise


async def get_feature(feature_id: int, layer_id: int = DEFAULT_LAYER_ID):
    return await send_request(
        "GET",
        f"/resource/{layer_id}/feature/{feature_id}/"
    )

@app.get(
    "/features/",
    tags=["Объекты"],
    summary="Получить объекты с фильтрацией",
    response_model=List[Dict],
)
async def get_all_features(
    request: Request,
    layer_id: int = DEFAULT_LAYER_ID
):
    params = dict(request.query_params)
    return await send_request(
        "GET",
        f"/resource/{layer_id}/feature/",
        params=params
    )

@app.get(
    "/features/bbox/",
    tags=["Объекты"],
    summary="Получить объекты в bounding box",
    response_model=List[Dict],
)
async def get_features_by_bbox(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    layer_id: int = DEFAULT_LAYER_ID
):
    return await send_request(
        "GET",
        f"/resource/{layer_id}/feature/",
        params={"bbox": f"{minx},{miny},{maxx},{maxy}"}
    )

@app.post("/upload/", tags=["Файлы"], summary="Загрузить файл")
async def upload_file(file: UploadFile = File(...), filename: str = "file"):
    try:
        content = await file.read()
        return await send_request(
            "POST",
            "/component/file_upload/",
            data={"name": filename},
            files={"file": (file.filename, content, file.content_type)}
        )
    finally:
        await file.close()

@app.post("/features/{feature_id}/attachments/", tags=["Вложения"])
async def attach_file(attachment: FileAttachment, feature_id: int, layer_id: int = DEFAULT_LAYER_ID):
    return await send_request(
        "POST",
        f"/resource/{layer_id}/feature/{feature_id}/attachment/",
        json_data=attachment.dict()
    )

@app.put("/features/{feature_id}/", tags=["Объекты"])
async def update_feature(feature: GeoFeature, feature_id: int, layer_id: int = DEFAULT_LAYER_ID):
    return await send_request(
        "PUT",
        f"/resource/{layer_id}/feature/{feature_id}",
        json_data=feature.dict()
    )

@app.delete("/features/", tags=["Объекты"], summary="Удалить объекты")
async def delete_features(feature_ids: List[int], layer_id: int = DEFAULT_LAYER_ID):
    if not feature_ids:
        raise HTTPException(status_code=400, detail="Не указаны ID объектов")
    
    return await send_request(
        "DELETE",
        f"/resource/{layer_id}/feature/",
        json_data=[{"id": fid} for fid in feature_ids]
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)