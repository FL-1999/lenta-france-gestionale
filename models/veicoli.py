from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Veicolo(Base):
    __tablename__ = "veicoli"

    id = Column(Integer, primary_key=True)

    # Dati principali
    marca = Column(String(120), nullable=False)
    modello = Column(String(120), nullable=False)
    targa = Column(String(50), nullable=False, unique=True)

    anno = Column(Integer)
    km = Column(Integer)

    # Nuovi campi
    carburante = Column(String(50))  # es. diesel, benzina, elettrico, ibrido...
    assicurazione_scadenza = Column(Date, nullable=True)
    revisione_scadenza = Column(Date, nullable=True)

    # Collegamento al personale (facoltativo)
    assegnato_a_id = Column(Integer, ForeignKey("personale.id"), nullable=True)
    assegnato_a = relationship("Personale", backref="veicoli_assegnati")

    note = Column(Text)

    def __repr__(self) -> str:
        return f"<Veicolo id={self.id} targa={self.targa}>"
