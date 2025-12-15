from sqlalchemy import Column, Integer, String, Text

from database import Base


class Veicolo(Base):
    __tablename__ = "veicoli"

    id = Column(Integer, primary_key=True)
    marca = Column(String(120), nullable=False)
    modello = Column(String(120), nullable=False)
    targa = Column(String(50), nullable=False, unique=True)
    anno = Column(Integer)
    km = Column(Integer)
    note = Column(Text)

    def __repr__(self) -> str:
        return f"<Veicolo id={self.id} targa={self.targa}>"
