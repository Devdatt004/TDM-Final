from abc import ABC, abstractmethod


class BaseConnector(ABC):

    @abstractmethod
    def connect(self):
        raise NotImplementedError

    @abstractmethod
    def validate(self):
        raise NotImplementedError

    @abstractmethod
    def list_documents(self):
        raise NotImplementedError

    @abstractmethod
    def sample(self, document_name: str, limit: int = 100):
        raise NotImplementedError

    @abstractmethod
    def describe(self, document_name: str):
        raise NotImplementedError

    @abstractmethod
    def close(self):
        raise NotImplementedError