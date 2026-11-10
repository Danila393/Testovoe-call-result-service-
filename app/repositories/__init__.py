from app.repositories.mongo import MongoCallStore, MongoCampaignStore
from app.repositories.protocols import CallStore, CampaignStore

__all__ = ["CallStore", "CampaignStore", "MongoCallStore", "MongoCampaignStore"]
