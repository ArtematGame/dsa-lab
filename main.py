from fastapi import FastAPI, Request, Depends
from sqlalchemy.orm import Session
from datetime import datetime
from database import engine, Base, get_db
from models import Visit

# Создаем таблицы при старте приложения
Base.metadata.create_all(bind=engine)

app = FastAPI()

@app.get("/hello")
async def hello(request: Request, db: Session = Depends(get_db)):
    # Получаем текущее время
    current_time = datetime.utcnow()
    
    # Получаем IP-адрес клиента
    # Если используется прокси, может потребоваться другой способ получения IP
    client_ip = request.client.host
    
    # Создаем запись в таблице Visit
    visit = Visit(
        visit_time=current_time,
        ip_address=client_ip
    )
    db.add(visit)
    db.commit()
    
    return {"message": "Hello"}

@app.get("/")
async def root():
    return {"message": "Visit counter API. Go to /hello to record a visit."}