from sqlalchemy import Column, Integer, String, Text

from database import Base


class Personale(Base):
    __tablename__ = "personale"

    id = Column(Integer, primary_key=True)
    nome = Column(String(120), nullable=False)
    cognome = Column(String(120), nullable=False)
    ruolo = Column(String(120), nullable=True)
    telefono = Column(String(50))
    email = Column(String(120))
    note = Column(Text)

    def __repr__(self) -> str:
        return f"<Personale id={self.id} nome={self.nome} cognome={self.cognome}>"
