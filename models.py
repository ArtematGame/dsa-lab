from sqlalchemy import Column, Integer, DateTime, String
from datetime import datetime
from database import Base

class Visit(Base):
    __tablename__ = "visits"
    
    id = Column(Integer, primary_key=True, index=True)
    visit_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    ip_address = Column(String(45), nullable=False)  # IPv6 может быть до 45 символов
    
    def __repr__(self):
        return f"<Visit(id={self.id}, time={self.visit_time}, ip={self.ip_address})>"