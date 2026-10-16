from abc import ABC, abstractmethod


class CredentialProvider(ABC):

    @abstractmethod
    def resolve(self, credential_ref: str) -> dict:
        """
        Resolve a credential reference into connection credentials.

        Implementations must never persist credentials.
        """
        raise NotImplementedError