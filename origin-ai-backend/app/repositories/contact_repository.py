"""Repository access for owner-scoped contact records."""

from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.models.contact import Contact


class ContactRepository:
    """Data-access helper for user contact lookup and resolution."""

    @staticmethod
    def list_for_owner(db: Session, owner_id: str) -> List[Contact]:
        return db.query(Contact).filter(Contact.owner_id == owner_id).order_by(Contact.full_name.asc()).all()

    @staticmethod
    def get_by_id(db: Session, owner_id: str, contact_id: str) -> Optional[Contact]:
        return db.query(Contact).filter(Contact.owner_id == owner_id, Contact.id == contact_id).first()

    @staticmethod
    def search(db: Session, owner_id: str, query: str) -> List[Contact]:
        normalized = query.strip().lower()
        if not normalized:
            return ContactRepository.list_for_owner(db, owner_id)
        contacts = ContactRepository.list_for_owner(db, owner_id)
        return [
            contact
            for contact in contacts
            if normalized in (contact.full_name.lower() or "")
            or normalized in (contact.email_address.lower() or "")
            or normalized in (contact.organization.lower() if contact.organization else "")
            or any(normalized in alias.lower() for alias in (contact.aliases or []))
        ]

    @staticmethod
    def resolve(db: Session, owner_id: str, value: str) -> Optional[Contact]:
        normalized = value.strip().lower()
        if not normalized:
            return None
        for contact in ContactRepository.list_for_owner(db, owner_id):
            if contact.email_address.lower() == normalized:
                return contact
            if contact.full_name.lower() == normalized:
                return contact
            if any(alias.lower() == normalized for alias in (contact.aliases or [])):
                return contact
        return None


contact_repository = ContactRepository()
