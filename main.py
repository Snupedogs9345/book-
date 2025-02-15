from fastapi import FastAPI, HTTPException, UploadFile, File, status, Request, Depends
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
from datetime import datetime

# Импорты для работы с базой данных через SQLAlchemy
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime, func, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# ---------------------- Настройка логирования ----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------- Создание FastAPI приложения ----------------------
app = FastAPI(
    title="GIS API Gateway",
    description="API для работы с геоинформационной системой",
    version="2.0",
    docs_url="/docs",
    redoc_url=None
)

# ---------------------- Конфигурация внешнего GIS API ----------------------
BASE_URL = "https://geois2.orb.ru/api"
TIMEOUT = 30.0
CREDENTIALS = {
    "username": "hackathon_37",
    "password": "hackathon_37_25"
}
DEFAULT_LAYER_ID = 8863

# Папка для сохранения загружаемых файлов
IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True, parents=True)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME_TYPES = [
    "image/jpeg", "image/png",
    "image/gif", "image/svg+xml",
    "application/pdf"
]

# Подключаем статическую папку для изображений
app.mount("/images", StaticFiles(directory="images"), name="images")

# ---------------------- Pydantic-модели для работы с внешним GIS API ----------------------
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

class FeatureUpdateResponse(BaseModel):
    id: int
    version: int

class FeatureResponse(GeoFeature):
    id: int
    version: Optional[int] = None
    attachments: List[AttachmentResponse] = []

# ---------------------- Конфигурация базы данных (SQLite) ----------------------
SQLALCHEMY_DATABASE_URL = "sqlite:///./app.db"  # Для PostgreSQL измените строку подключения

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}  # Только для SQLite
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """
    Зависимость для получения сессии базы данных.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------------- Нормализованные модели базы данных ----------------------
# Таблица для фич (features)
class FeatureDB(Base):
    __tablename__ = "features"
    id = Column(Integer, primary_key=True, index=True)  # внутренняя БД ID
    external_id = Column(Integer, unique=True, nullable=False)  # ID из внешней системы
    geom = Column(String, nullable=False)
    version = Column(Integer, nullable=True)
    description = Column(String, nullable=True)  # extensions.description

    # Распаковываем поля из "fields"
    fid_1 = Column(String, nullable=True)
    num = Column(Integer, nullable=True)
    n_raion = Column(String, nullable=True)
    fio = Column(String, nullable=True)
    years = Column(String, nullable=True)
    info = Column(String, nullable=True)
    kontrakt = Column(String, nullable=True)
    nagrads = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связь с вложениями
    attachments = relationship("AttachmentDB", back_populates="feature", cascade="all, delete-orphan")

# Таблица для вложений (attachments)
class AttachmentDB(Base):
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, nullable=False)  # ID вложения из внешней системы
    feature_id = Column(Integer, ForeignKey("features.id"), nullable=False)
    name = Column(String, nullable=False)
    keyname = Column(String, nullable=True)
    size = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_image = Column(Boolean, nullable=False)
    file_meta = Column(JSON, nullable=True)

    feature = relationship("FeatureDB", back_populates="attachments")

# Создаем таблицы в базе данных (если их ещё нет)
Base.metadata.create_all(bind=engine)

# ---------------------- Pydantic-схемы для нормализованных данных ----------------------
class AttachmentResponseDB(BaseModel):
    id: int
    external_id: int
    name: str
    keyname: Optional[str] = None
    size: int
    mime_type: str
    description: Optional[str] = None
    is_image: bool
    file_meta: Dict = {}

    class Config:
        orm_mode = True

class FeatureResponseNormalized(BaseModel):
    id: int
    external_id: int
    geom: str
    version: Optional[int] = None
    description: Optional[str] = None
    fid_1: Optional[str] = None
    num: Optional[int] = None
    n_raion: Optional[str] = None
    fio: Optional[str] = None
    years: Optional[str] = None
    info: Optional[str] = None
    kontrakt: Optional[str] = None
    nagrads: Optional[str] = None
    created_at: datetime
    attachments: List[AttachmentResponseDB] = []

    class Config:
        orm_mode = True

# ---------------------- Pydantic-модели для входных данных (полный JSON из внешней системы) ----------------------
class ExternalAttachment(BaseModel):
    id: int
    name: str
    keyname: Optional[str] = None
    size: int
    mime_type: str
    description: Optional[str] = None
    is_image: bool
    file_meta: Dict = {}

class ExternalExtensions(BaseModel):
    description: Optional[str] = None
    attachment: List[ExternalAttachment] = []

class ExternalFields(BaseModel):
    fid_1: Optional[str] = None
    num: Optional[int] = None
    n_raion: Optional[str] = None
    fio: Optional[str] = None
    years: Optional[str] = None
    info: Optional[str] = None
    kontrakt: Optional[str] = None
    nagrads: Optional[str] = None

class ExternalFeature(BaseModel):
    extensions: ExternalExtensions
    fields: ExternalFields
    geom: str
    id: int
    version: Optional[int] = None
    attachments: List[ExternalAttachment] = []  # может быть пустым

# ---------------------- Служебные функции для работы с внешним API ----------------------
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
            logger.info(f"Sending request to {endpoint}")
            response = await client.request(
                method=method,
                url=f"{BASE_URL}{endpoint}",
                data=data,
                files=files,
                json=json_data,
                params=params
            )
            logger.debug(f"Response content: {response.text}")
            response.raise_for_status()
            if "application/json" in response.headers.get("content-type", ""):
                return response.json()
            return {"status": "success", "response": response.text}
    except httpx.HTTPStatusError as e:
        logger.error(f"API error: {e.response.text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Ошибка API: {e.response.text}"
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

# ---------------------- Эндпоинты для работы с внешним GIS API (с автоматической синхронизацией в локальную БД) ----------------------
# GET /features/ (получение объектов из внешней системы с синхронизацией в локальную БД)
@app.get("/features/", response_model=List[FeatureResponse], tags=["Объекты"], operation_id="getFeatures")
async def get_all_features(
    request: Request,
    layer_id: int = DEFAULT_LAYER_ID,
    kontrakt: Optional[str] = None,
    n_raion: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Получить объекты с фильтрацией во внешней системе и синхронизировать их с локальной БД.
    Параметры:
      - kontrakt: точное совпадение места службы (например: СВО)
      - n_raion: точное совпадение района (например: Тюльганский район)
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
    if not isinstance(response, list):
        logger.error(f"Некорректный ответ от API: {response}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка получения объектов"
        )
    # Фильтрация (на случай, если внешняя система не учла параметры)
    filtered_response = response
    if kontrakt:
        filtered_response = [item for item in filtered_response if item.get("fields", {}).get("kontrakt") == kontrakt]
    if n_raion:
        filtered_response = [item for item in filtered_response if item.get("fields", {}).get("n_raion") == n_raion]
    
    # Синхронизация каждого объекта с локальной БД
    for feature_data in filtered_response:
        external_id = feature_data.get("id")
        fields = feature_data.get("fields", {})
        extensions = feature_data.get("extensions", {})
        local_feature = db.query(FeatureDB).filter(FeatureDB.external_id == external_id).first()
        if local_feature:
            local_feature.geom = feature_data.get("geom")
            local_feature.version = feature_data.get("version")
            local_feature.description = extensions.get("description")
            local_feature.fid_1 = fields.get("fid_1")
            local_feature.num = fields.get("num")
            local_feature.n_raion = fields.get("n_raion")
            local_feature.fio = fields.get("fio")
            local_feature.years = fields.get("years")
            local_feature.info = fields.get("info")
            local_feature.kontrakt = fields.get("kontrakt")
            local_feature.nagrads = fields.get("nagrads")
            db.commit()
            db.refresh(local_feature)
        else:
            new_feature = FeatureDB(
                external_id=external_id,
                geom=feature_data.get("geom"),
                version=feature_data.get("version"),
                description=extensions.get("description"),
                fid_1=fields.get("fid_1"),
                num=fields.get("num"),
                n_raion=fields.get("n_raion"),
                fio=fields.get("fio"),
                years=fields.get("years"),
                info=fields.get("info"),
                kontrakt=fields.get("kontrakt"),
                nagrads=fields.get("nagrads"),
            )
            db.add(new_feature)
            db.commit()
            db.refresh(new_feature)
            local_feature = new_feature

        # Синхронизация вложений из top-level "attachments" и "extensions.attachment"
        top_level_attachments = feature_data.get("attachments") or []
        extension_attachments = extensions.get("attachment") or []
        all_attachments = top_level_attachments + extension_attachments

        for att in all_attachments:
            external_att_id = att.get("id")
            local_attachment = db.query(AttachmentDB).filter(
                AttachmentDB.feature_id == local_feature.id,
                AttachmentDB.external_id == external_att_id
            ).first()
            if local_attachment:
                local_attachment.name = att.get("name")
                local_attachment.keyname = att.get("keyname")
                local_attachment.size = att.get("size")
                local_attachment.mime_type = att.get("mime_type")
                local_attachment.description = att.get("description")
                local_attachment.is_image = att.get("is_image")
                local_attachment.file_meta = att.get("file_meta")
                db.commit()
                db.refresh(local_attachment)
            else:
                new_attachment = AttachmentDB(
                    external_id=external_att_id,
                    feature_id=local_feature.id,
                    name=att.get("name"),
                    keyname=att.get("keyname"),
                    size=att.get("size"),
                    mime_type=att.get("mime_type"),
                    description=att.get("description"),
                    is_image=att.get("is_image"),
                    file_meta=att.get("file_meta")
                )
                db.add(new_attachment)
                db.commit()
                db.refresh(new_attachment)

    return filtered_response

# Новый маршрут для загрузки вложения
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

# POST /features/ (создание объекта во внешней системе и автоматическая синхронизация в локальной БД)
@app.post("/features/", response_model=FeatureCreateResponse, tags=["Объекты"], operation_id="createFeature")
async def create_feature(feature: GeoFeature, layer_id: int = DEFAULT_LAYER_ID, db: Session = Depends(get_db)):
    response = await send_request(
        "POST",
        f"/resource/{layer_id}/feature/",
        json_data=feature.dict()
    )
    if not isinstance(response, dict) or 'id' not in response:
        logger.error(f"Некорректный ответ от API: {response}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка создания объекта"
        )
    external_id = response["id"]
    new_feature = FeatureDB(
        external_id=external_id,
        geom=feature.geom,
        version=response.get("version"),
        description=feature.extensions.get("description"),
        fid_1=feature.fields.get("fid_1"),
        num=feature.fields.get("num"),
        n_raion=feature.fields.get("n_raion"),
        fio=feature.fields.get("fio"),
        years=feature.fields.get("years"),
        info=feature.fields.get("info"),
        kontrakt=feature.fields.get("kontrakt"),
        nagrads=feature.fields.get("nagrads"),
    )
    db.add(new_feature)
    db.commit()
    db.refresh(new_feature)

    # Если во входном объекте во "extensions.attachment" есть вложения, сохраним их
    if feature.extensions.get("attachment"):
        for att in feature.extensions["attachment"]:
            new_attachment = AttachmentDB(
                external_id=att.get("id", 0),
                feature_id=new_feature.id,
                name=att.get("name"),
                keyname=att.get("keyname"),
                size=att.get("size", 0),
                mime_type=att.get("mime_type"),
                description=att.get("description"),
                is_image=att.get("is_image"),
                file_meta=att.get("file_meta", {})
            )
            db.add(new_attachment)
        db.commit()

    return response

# PUT /features/{feature_id}/ (обновление объекта)
@app.put("/features/{feature_id}/", response_model=FeatureUpdateResponse, tags=["Объекты"], operation_id="updateFeature")
async def update_feature(feature_id: int, feature: GeoFeature, layer_id: int = DEFAULT_LAYER_ID, db: Session = Depends(get_db)):
    response = await send_request(
        "PUT",
        f"/resource/{layer_id}/feature/{feature_id}",
        json_data=feature.dict()
    )
    if not isinstance(response, dict) or 'id' not in response:
        logger.error(f"Некорректный ответ от API: {response}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка обновления объекта"
        )
    local_feature = db.query(FeatureDB).filter(FeatureDB.external_id == feature_id).first()
    if local_feature:
        local_feature.geom = feature.geom
        local_feature.version = response.get("version")
        local_feature.description = feature.extensions.get("description")
        local_feature.fid_1 = feature.fields.get("fid_1")
        local_feature.num = feature.fields.get("num")
        local_feature.n_raion = feature.fields.get("n_raion")
        local_feature.fio = feature.fields.get("fio")
        local_feature.years = feature.fields.get("years")
        local_feature.info = feature.fields.get("info")
        local_feature.kontrakt = feature.fields.get("kontrakt")
        local_feature.nagrads = feature.fields.get("nagrads")
        db.commit()
        db.refresh(local_feature)
    else:
        new_feature = FeatureDB(
            external_id=feature_id,
            geom=feature.geom,
            version=response.get("version"),
            description=feature.extensions.get("description"),
            fid_1=feature.fields.get("fid_1"),
            num=feature.fields.get("num"),
            n_raion=feature.fields.get("n_raion"),
            fio=feature.fields.get("fio"),
            years=feature.fields.get("years"),
            info=feature.fields.get("info"),
            kontrakt=feature.fields.get("kontrakt"),
            nagrads=feature.fields.get("nagrads"),
        )
        db.add(new_feature)
        db.commit()
        db.refresh(new_feature)
    return response

# GET /features/{feature_id} (получение объекта и синхронизация вложений)
@app.get("/features/{feature_id}", response_model=FeatureResponse, tags=["Объекты"], operation_id="getFeature")
async def get_feature(feature_id: int, layer_id: int = DEFAULT_LAYER_ID, db: Session = Depends(get_db)):
    response = await send_request(
        "GET",
        f"/resource/{layer_id}/feature/{feature_id}"
    )
    if not isinstance(response, dict) or 'fields' not in response:
        logger.error(f"Некорректный ответ от API: {response}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка получения объекта"
        )
    fields = response.get("fields", {})
    extensions = response.get("extensions", {})
    local_feature = db.query(FeatureDB).filter(FeatureDB.external_id == feature_id).first()
    if local_feature:
        local_feature.geom = response.get("geom")
        local_feature.version = response.get("version")
        local_feature.description = extensions.get("description")
        local_feature.fid_1 = fields.get("fid_1")
        local_feature.num = fields.get("num")
        local_feature.n_raion = fields.get("n_raion")
        local_feature.fio = fields.get("fio")
        local_feature.years = fields.get("years")
        local_feature.info = fields.get("info")
        local_feature.kontrakt = fields.get("kontrakt")
        local_feature.nagrads = fields.get("nagrads")
        db.commit()
        db.refresh(local_feature)
    else:
        new_feature = FeatureDB(
            external_id=feature_id,
            geom=response.get("geom"),
            version=response.get("version"),
            description=extensions.get("description"),
            fid_1=fields.get("fid_1"),
            num=fields.get("num"),
            n_raion=fields.get("n_raion"),
            fio=fields.get("fio"),
            years=fields.get("years"),
            info=fields.get("info"),
            kontrakt=fields.get("kontrakt"),
            nagrads=fields.get("nagrads"),
        )
        db.add(new_feature)
        db.commit()
        db.refresh(new_feature)
        local_feature = new_feature

    # Синхронизация вложений из top-level "attachments" и "extensions.attachment"
    top_level_attachments = response.get("attachments") or []
    extension_attachments = extensions.get("attachment") or []
    all_attachments = top_level_attachments + extension_attachments

    for att in all_attachments:
        external_att_id = att.get("id")
        local_attachment = db.query(AttachmentDB).filter(
            AttachmentDB.feature_id == local_feature.id,
            AttachmentDB.external_id == external_att_id
        ).first()
        if local_attachment:
            local_attachment.name = att.get("name")
            local_attachment.keyname = att.get("keyname")
            local_attachment.size = att.get("size")
            local_attachment.mime_type = att.get("mime_type")
            local_attachment.description = att.get("description")
            local_attachment.is_image = att.get("is_image")
            local_attachment.file_meta = att.get("file_meta")
            db.commit()
            db.refresh(local_attachment)
        else:
            new_attachment = AttachmentDB(
                external_id=external_att_id,
                feature_id=local_feature.id,
                name=att.get("name"),
                keyname=att.get("keyname"),
                size=att.get("size"),
                mime_type=att.get("mime_type"),
                description=att.get("description"),
                is_image=att.get("is_image"),
                file_meta=att.get("file_meta")
            )
            db.add(new_attachment)
            db.commit()
            db.refresh(new_attachment)

    return response

# DELETE /features/ (удаление объектов)
@app.delete("/features/", tags=["Объекты"], operation_id="deleteFeatures")
async def delete_features(feature_ids: List[int], layer_id: int = DEFAULT_LAYER_ID, db: Session = Depends(get_db)):
    if not feature_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не указаны ID объектов"
        )
    response = await send_request(
        "DELETE",
        f"/resource/{layer_id}/feature/",
        json_data=[{"id": fid} for fid in feature_ids]
    )
    for fid in feature_ids:
        local_feature = db.query(FeatureDB).filter(FeatureDB.external_id == fid).first()
        if local_feature:
            db.delete(local_feature)
    db.commit()
    return response

# DELETE /features/{feature_id}/attachments/{attachment_id} (удаление вложения)
@app.delete("/features/{feature_id}/attachments/{attachment_id}", tags=["Вложения"], operation_id="deleteAttachment")
async def delete_attachment(feature_id: int, attachment_id: str, layer_id: int = DEFAULT_LAYER_ID, db: Session = Depends(get_db)):
    response = await send_request(
        "DELETE",
        f"/resource/{layer_id}/feature/{feature_id}/attachment/{attachment_id}"
    )
    local_attachment = db.query(AttachmentDB).filter(
        AttachmentDB.feature_id == feature_id,
        AttachmentDB.external_id == int(attachment_id)
    ).first()
    if local_attachment:
        db.delete(local_attachment)
        db.commit()
    return response

# Дополнительный эндпоинт для синхронизации полного JSON (если нужно)
@app.post("/db/sync-feature/", response_model=FeatureResponseNormalized, tags=["Локальная БД"], operation_id="syncFeature")
def sync_feature(feature: ExternalFeature, db: Session = Depends(get_db)):
    new_feature = FeatureDB(
        external_id=feature.id,
        geom=feature.geom,
        version=feature.version,
        description=feature.extensions.description,
        fid_1=feature.fields.fid_1,
        num=feature.fields.num,
        n_raion=feature.fields.n_raion,
        fio=feature.fields.fio,
        years=feature.fields.years,
        info=feature.fields.info,
        kontrakt=feature.fields.kontrakt,
        nagrads=feature.fields.nagrads,
    )
    db.add(new_feature)
    db.commit()
    db.refresh(new_feature)
    for att in feature.extensions.attachment:
        new_attachment = AttachmentDB(
            external_id=att.id,
            feature_id=new_feature.id,
            name=att.name,
            keyname=att.keyname,
            size=att.size,
            mime_type=att.mime_type,
            description=att.description,
            is_image=att.is_image,
            file_meta=att.file_meta,
        )
        db.add(new_attachment)
    db.commit()
    db.refresh(new_feature)
    return new_feature

@app.get("/db/features/{feature_id}", response_model=FeatureResponseNormalized, tags=["Локальная БД"], operation_id="readDBFeature")
def read_feature(feature_id: int, db: Session = Depends(get_db)):
    feature = db.query(FeatureDB).filter(FeatureDB.id == feature_id).first()
    if not feature:
        raise HTTPException(status_code=404, detail="Объект не найден")
    return feature

@app.get("/db/features/", response_model=List[FeatureResponseNormalized], tags=["Локальная БД"], operation_id="readDBFeatures")
def read_features(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    features = db.query(FeatureDB).offset(skip).limit(limit).all()
    return features

# ---------------------- Запуск приложения ----------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
