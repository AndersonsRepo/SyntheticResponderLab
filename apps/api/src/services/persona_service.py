from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.persistence.models import Persona
from src.persistence.persona_seed import persona_cards


def list_personas(session: Session) -> List[dict]:
    personas = session.scalars(select(Persona).order_by(Persona.row_index)).all()
    cards = persona_cards()
    return [{**persona.profile_json, "card": cards.get(persona.persona_id)} for persona in personas]
